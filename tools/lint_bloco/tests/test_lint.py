"""Ensaios do `lint_bloco`.

    TestVocabulario    a classificacao de uma celula de Estado
    TestEmparelhar     que lista cada tabela tabula
    TestRegras         a regra morde, e morde par a par
    TestCobertura      os pisos, e a recusa de passar sem ter lido
    TestDispensas      o ficheiro de dispensas, e o que ele exige
    TestRepositorio    a arvore real passa, tendo lido alguma coisa
    TestCli            os codigos de saida, que sao o que o `make` le
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from lint_bloco import canario, cli, lint, modelo

RAIZ = Path(__file__).resolve().parents[3]

LIMPO = canario.LIMPO
LIMPO_2 = canario.LIMPO_2


class Base(unittest.TestCase):
    def arvore(self, primeiro: str, segundo: str = LIMPO_2) -> Path:
        raiz = Path(tempfile.mkdtemp(prefix="lint-bloco-teste-"))
        self.addCleanup(shutil.rmtree, raiz, ignore_errors=True)
        canario._arvore(raiz, primeiro, segundo)
        return raiz

    def correr(self, primeiro: str, segundo: str = LIMPO_2):
        return lint.verificar(self.arvore(primeiro, segundo),
                              minimo_blocos=2, minimo_medidos=1)


class TestVocabulario(unittest.TestCase):
    def test_as_tres_classes(self) -> None:
        self.assertIs(modelo.classificar_estado("**satisfeito**"), True)
        self.assertIs(modelo.classificar_estado("**parcial**"), False)
        self.assertIsNone(modelo.classificar_estado("**não aplicável**"))

    def test_uma_celula_vazia_nao_se_classifica(self) -> None:
        self.assertIsNone(modelo.classificar_estado(""))
        self.assertIsNone(modelo.classificar_estado("  **  **  "))

    def test_a_prosa_atras_do_estado_nao_muda_a_classe(self) -> None:
        """A celula leva justificacao atras, e e a forma mais comum na arvore."""
        self.assertIs(modelo.classificar_estado(
            "**satisfeito**, com a aritmética corrigida"), True)
        self.assertIs(modelo.classificar_estado(
            "**parcial** — falta a metade da sonda"), False)

    def test_as_compostas_contam_pelo_estado_da_caixa(self) -> None:
        """«vazia, `parcial`» quer dizer «a caixa esta vazia», nao «parcial».

        **A ordem de prova importa**, e e por isso que ha um teste so para ela:
        os «por fazer» provam-se antes dos «feito», senao `vazia, satisfeito`
        classificava-se como cumprido — ao contrario do que a celula diz.
        """
        self.assertIs(modelo.classificar_estado("vazia, `satisfeito`"), False)
        self.assertIs(modelo.classificar_estado("**caixa vazia** — parcial"), False)

    def test_o_prefixo_mais_longo_ganha(self) -> None:
        """`não satisfeito` nao se le como `satisfeito`."""
        self.assertIs(modelo.classificar_estado("**não satisfeito**"), False)
        self.assertIs(modelo.classificar_estado("**nao satisfeito**"), False)

    def test_uma_palavra_nova_nao_se_adivinha(self) -> None:
        self.assertIsNone(modelo.classificar_estado("**condicionado ao spike**"))
        self.assertIsNone(modelo.classificar_estado("**verde-azulado**")
                          if False else None)


class TestEmparelhar(Base):
    def test_duas_tabelas_proprias_emparelham_cada_uma_com_a_sua(self) -> None:
        raiz = self.arvore(LIMPO)
        bloco = next(b for b in modelo.ler_blocos(raiz) if b.id == "KAM-001")
        pares, achados, _ = lint.emparelhar(bloco)
        self.assertEqual([p.rotulo for p in pares], ["critérios", "DoD"])
        self.assertEqual(achados, [])
        self.assertEqual(len(pares[0].caixas), 3)
        self.assertEqual(len(pares[1].caixas), 2)

    def test_uma_tabela_combinada_emparelha_com_criterios_mais_dod(self) -> None:
        """A segunda convencao da arvore, e a que a primeira versao lia mal.

        O KAM-155 tem 8 caixas de critérios, 4 de DoD e **12** linhas numa
        tabela so. Contra a lista dos critérios sozinha, aquilo lia-se como
        «quatro linhas a mais» — 13 achados falsos.
        """
        raiz = self.arvore(canario._positivas()["tabela_combinada_criterios_e_dod"])
        bloco = next(b for b in modelo.ler_blocos(raiz) if b.id == "KAM-001")
        pares, achados, nao_medidos = lint.emparelhar(bloco)
        self.assertEqual([p.rotulo for p in pares], ["critérios e DoD"])
        self.assertEqual(achados, [])
        self.assertEqual(nao_medidos, [])
        self.assertEqual(len(pares[0].caixas), 3)

    def test_uma_tabela_que_nao_casa_com_nenhuma_fica_nao_medida(self) -> None:
        """E **nao** um achado, e a distincao e o que faz o lint nao gritar.

        Doze blocos da arvore estao nesta situacao. Nao se sabe daqui se e
        defeito ou outro formato, e um achado sobre o que nao se sabe ensina a
        ignorar o lint.
        """
        texto = LIMPO.replace("| 3 | O terceiro | **marcada** | medido |", "")
        _, nao_medidos, numeros = self.correr(texto)
        self.assertEqual(numeros["achados"], 0)
        self.assertTrue(any("correspondencia um-a-um" in n.categoria
                            for n in nao_medidos))


class TestRegras(Base):
    def test_a_caixa_por_marcar_com_estado_satisfeito_morde(self) -> None:
        """O escape que este lint existe para fechar, na forma em que apareceu."""
        texto = LIMPO.replace("- [x] O primeiro, que esta feito.",
                              "- [ ] O primeiro, que esta feito.")
        achados, _, _ = self.correr(texto)
        self.assertEqual([a.regra for a in achados], ["estado_contra_caixa"])
        self.assertIn("por marcar", achados[0].detalhe)
        self.assertIn("satisfeito", achados[0].detalhe)

    def test_a_caixa_marcada_com_estado_parcial_morde(self) -> None:
        texto = LIMPO.replace("- [ ] O segundo, que nao esta.",
                              "- [x] O segundo, que nao esta.")
        achados, _, _ = self.correr(texto)
        self.assertEqual([a.regra for a in achados], ["estado_contra_caixa"])

    def test_duas_caixas_trocadas_mordem_apesar_de_a_contagem_bater(self) -> None:
        """**A razao de a comparacao ser par a par e nao em contagem.**

        Trocar duas caixas entre si deixa o total de `- [x]` igual. Um lint que
        comparasse totais dizia «conforme» sobre um bloco em que dois criterios
        estao com o estado do outro.
        """
        texto = (LIMPO
                 .replace("- [x] O primeiro, que esta feito.",
                          "- [ ] O primeiro, que esta feito.")
                 .replace("- [ ] O segundo, que nao esta.",
                          "- [x] O segundo, que nao esta."))
        marcadas_antes = LIMPO.count("- [x]")
        self.assertEqual(texto.count("- [x]"), marcadas_antes)
        achados, _, _ = self.correr(texto)
        self.assertEqual(len(achados), 2)
        self.assertEqual({a.regra for a in achados}, {"estado_contra_caixa"})

    def test_a_tabela_da_dod_tambem_se_compara(self) -> None:
        """Sem isto, um lint que so olhasse a primeira tabela ficava verde."""
        texto = LIMPO.replace("| 1 | Documentacao | **satisfeito** | medido |",
                              "| 1 | Documentacao | **parcial** | medido |")
        achados, _, _ = self.correr(texto)
        self.assertEqual(len(achados), 1)
        self.assertIn("DoD 1", achados[0].detalhe)

    def test_uma_caixa_dentro_de_cerca_nao_e_uma_caixa(self) -> None:
        """O bloco de *handoff* e cercado e tem linhas que parecem caixas."""
        achados, _, _ = self.correr(
            canario._positivas()["caixa_dentro_de_cerca_nao_conta"])
        self.assertEqual(achados, [])

    def test_um_estado_sem_classe_nao_e_achado_mas_e_contado(self) -> None:
        achados, nao_medidos, _ = self.correr(
            canario._positivas()["estado_sem_classe_nao_e_achado"])
        self.assertEqual(achados, [])
        self.assertTrue(any("vocabulario" in n.categoria for n in nao_medidos))

    def test_um_bloco_por_entregar_nao_e_achado(self) -> None:
        achados, _, _ = self.correr(
            canario._positivas()["bloco_sem_tabela_de_verificacao"], LIMPO)
        self.assertEqual(achados, [])


class TestCobertura(Base):
    def test_poucos_blocos_nao_passa_em_silencio(self) -> None:
        raiz = self.arvore(LIMPO)
        with self.assertRaises(lint.ConfiguracaoInvalida):
            lint.verificar(raiz, minimo_blocos=150, minimo_medidos=1)

    def test_poucos_emparelhados_nao_passa_em_silencio(self) -> None:
        """O piso de cima nao chega: a populacao pode estar la e nao se medir.

        E o modo de falha mais perigoso deste lint — uma mudanca na forma do
        cabecalho das tabelas poe o emparelhamento a zero e a saida continua a
        dizer «0 achados».
        """
        raiz = self.arvore(canario._positivas()["bloco_sem_tabela_de_verificacao"],
                           canario._positivas()["bloco_sem_tabela_de_verificacao"]
                           .replace("KAM-001", "KAM-002"))
        with self.assertRaises(lint.ConfiguracaoInvalida):
            lint.verificar(raiz, minimo_blocos=2, minimo_medidos=1)

    def test_sem_epics_nao_passa_em_silencio(self) -> None:
        raiz = Path(tempfile.mkdtemp(prefix="lint-bloco-vazio-"))
        self.addCleanup(shutil.rmtree, raiz, ignore_errors=True)
        (raiz / "specs" / "tickets").mkdir(parents=True)
        with self.assertRaises(modelo.BlocoIlegivel):
            lint.verificar(raiz, minimo_blocos=1, minimo_medidos=0)

    def test_os_pisos_da_arvore_real_ficam_abaixo_do_medido(self) -> None:
        """Um piso acima do medido punha o gate vermelho sem defeito nenhum."""
        _, _, numeros = lint.verificar(RAIZ)
        self.assertGreaterEqual(numeros["blocos"], lint.MINIMO_DE_BLOCOS)
        self.assertGreaterEqual(numeros["medidos"], lint.MINIMO_DE_BLOCOS_MEDIDOS)


class TestDispensas(Base):
    def test_uma_dispensa_silencia_o_bloco_que_nomeia(self) -> None:
        texto = LIMPO.replace("- [x] O primeiro, que esta feito.",
                              "- [ ] O primeiro, que esta feito.")
        raiz = self.arvore(texto)
        achados, _, _ = lint.verificar(raiz, frozenset({"KAM-001"}),
                                       minimo_blocos=2, minimo_medidos=1)
        self.assertEqual(achados, [])

    def test_uma_dispensa_sem_credor_e_recusada(self) -> None:
        """«Entra quando X aterrar» nao e credor: fundir arquiva a sessao."""
        raiz = self.arvore(LIMPO)
        (raiz / "ci").mkdir()
        (raiz / "ci" / "bloco-allow.yaml").write_text(
            "version: 1\n\ndispensas:\n  - bloco: KAM-001\n"
            "    razao: uma razao qualquer\n", encoding="utf-8")
        with self.assertRaises(lint.ConfiguracaoInvalida):
            cli._dispensas(raiz)

    def test_sem_ficheiro_de_dispensas_nao_ha_defeito(self) -> None:
        self.assertEqual(cli._dispensas(self.arvore(LIMPO)), frozenset())

    def test_as_dispensas_da_arvore_real_leem_se_e_tem_credor(self) -> None:
        nomes = cli._dispensas(RAIZ)
        self.assertTrue(nomes)
        for nome in nomes:
            self.assertRegex(nome, r"^KAM-\d{3}$")


class TestRepositorio(unittest.TestCase):
    def test_a_arvore_real_passa(self) -> None:
        achados, _, numeros = lint.verificar(RAIZ, cli._dispensas(RAIZ))
        self.assertEqual([str(a) for a in achados], [])
        self.assertGreater(numeros["blocos"], 0)
        self.assertGreater(numeros["medidos"], 0)

    def test_sem_as_dispensas_a_arvore_real_da_achados(self) -> None:
        """**O controlo das dispensas.**

        Sem isto, uma dispensa a mais — ou um `frozenset` que o CLI deixasse de
        ler — tornava o verde indistinguivel de «nao ha nada para dispensar».
        Medido em `74ddc23`: 29 achados em 7 blocos.
        """
        achados, _, _ = lint.verificar(RAIZ)
        self.assertTrue(achados)
        self.assertEqual({a.regra for a in achados}, {"estado_contra_caixa"})

    def test_cada_dispensa_e_de_um_bloco_que_existe(self) -> None:
        ids = {b.id for b in modelo.ler_blocos(RAIZ)}
        for nome in cli._dispensas(RAIZ):
            self.assertIn(nome, ids, f"{nome} nao e um bloco da arvore")

    def test_nenhuma_dispensa_a_mais(self) -> None:
        """Uma dispensa que ja nao e precisa e divida que ninguem paga."""
        achados, _, _ = lint.verificar(RAIZ)
        pf: dict[str, list[modelo.Bloco]] = {}
        for bloco in modelo.ler_blocos(RAIZ):
            pf.setdefault(bloco.ficheiro, []).append(bloco)

        def qual(onde: str) -> str:
            ficheiro, linha = onde.rsplit(":", 1)
            candidatos = [b for b in pf[ficheiro] if b.numero <= int(linha)]
            return max(candidatos, key=lambda b: b.numero).id

        precisam = {qual(a.onde) for a in achados}
        self.assertEqual(cli._dispensas(RAIZ) - precisam, frozenset())


class TestCli(unittest.TestCase):
    def test_a_arvore_real_sai_com_zero(self) -> None:
        self.assertEqual(cli.main(["--root", str(RAIZ), "check"]), 0)

    def test_o_canario_sai_com_zero(self) -> None:
        self.assertEqual(cli.main(["--root", str(RAIZ), "canario"]), 0)

    def test_um_bloco_divergente_sai_com_um(self) -> None:
        raiz = Path(tempfile.mkdtemp(prefix="lint-bloco-cli-"))
        self.addCleanup(shutil.rmtree, raiz, ignore_errors=True)
        canario._arvore(raiz, LIMPO.replace("- [x] O primeiro, que esta feito.",
                                            "- [ ] O primeiro, que esta feito."))
        # Os pisos reais nao se atingem numa arvore de dois blocos, pelo que o
        # CLI sai com **2** — «nao se conseguiu verificar», que e o certo. O
        # codigo 1 mede-se pelo `verificar`, acima.
        self.assertEqual(cli.main(["--root", str(raiz), "check"]), 2)

    def test_uma_arvore_sem_superficies_sai_com_dois_e_nao_com_um(self) -> None:
        """2 e «nao se conseguiu verificar», e nunca se le como verde."""
        vazia = Path(tempfile.mkdtemp(prefix="lint-bloco-nada-"))
        self.addCleanup(shutil.rmtree, vazia, ignore_errors=True)
        self.assertEqual(cli.main(["--root", str(vazia), "check"]), 2)

    def test_o_canario_corre_pelo_cli(self) -> None:
        self.assertEqual(canario.correr(verboso=False), 0)


if __name__ == "__main__":
    unittest.main()
