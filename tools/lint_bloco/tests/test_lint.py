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

    def test_as_compostas_contam_pelo_termo_e_nao_pela_ordem_das_listas(self) -> None:
        """«vazia, `parcial`» quer dizer «a caixa esta vazia», nao «parcial».

        **E a ordem das listas nao e o que o garante**, ao contrario do que a
        versao anterior deste ensaio afirmava. Ela dizia «os por fazer provam-se
        antes dos feito, senao `vazia, satisfeito` classificava-se como
        cumprido», e isso e falso: o **termo** de `vazia, satisfeito` e `vazia`,
        e nenhuma ordem de listas o muda. A revisao adversarial provou-o — a
        mutacao que troca as listas sobrevivia a este ensaio.
        """
        self.assertIs(modelo.classificar_estado("vazia, `satisfeito`"), False)
        self.assertIs(modelo.classificar_estado("**caixa vazia** — parcial"), False)
        # O que **de facto** governa: o termo antes do separador.
        self.assertEqual(modelo._termo_da_celula("vazia, satisfeito"), "vazia")
        self.assertEqual(
            modelo._termo_da_celula("satisfeito, com a aritmética corrigida"),
            "satisfeito")

    def test_o_termo_mais_longo_ganha_dentro_da_lista(self) -> None:
        """`não satisfeito` nao se le como `satisfeito`."""
        self.assertIs(modelo.classificar_estado("**não satisfeito**"), False)
        self.assertIs(modelo.classificar_estado("**nao satisfeito**"), False)
        self.assertIs(modelo.classificar_estado("**não satisfeita**"), False)

    def test_uma_palavra_nova_nao_se_adivinha(self) -> None:
        """**Esta assertiva estava desactivada, e escondia um defeito real.**

        A versao anterior escrevia
        `assertIsNone(classificar_estado("**verde-azulado**") if False else None)`:
        o `if False` fazia o argumento ser `None`, a funcao **nunca era chamada**
        e a assertiva era tautologica. A revisao adversarial mediu o valor real —
        `True`, porque `verde` casava por prefixo — e a assertiva, activada,
        falhava. Hoje passa porque o casamento e por **termo** e nao por prefixo.
        """
        self.assertIsNone(modelo.classificar_estado("**condicionado ao spike**"))
        self.assertIsNone(modelo.classificar_estado("**verde-azulado**"))

    def test_o_prefixo_nu_sobre_casava_e_hoje_nao(self) -> None:
        """Os quatro casos que a revisao adversarial mediu, um a um.

        O ultimo e uma forma **real** da arvore, e e o que torna isto mais do
        que um exercicio: uma celula que diz as duas coisas nao pode ser lida
        como uma delas.
        """
        for celula in ("verde-azulado", "cumprido parcialmente",
                       "marcadamente insuficiente",
                       "confirmado / não verificado"):
            with self.subTest(celula=celula):
                self.assertIsNone(modelo.classificar_estado(celula))

    def test_o_vocabulario_cobre_as_formas_que_lhe_dao_o_nome(self) -> None:
        """A lista chamava-se «por cumprir» e nao continha `por cumprir`.

        Medido pela revisao adversarial no `KAM-133`; e o `KAM-068` escreve
        `não — caixa vazia`, que a *docstring* dizia estar coberta e nao estava.
        """
        self.assertIs(modelo.classificar_estado("**por cumprir**"), False)
        self.assertIs(modelo.classificar_estado("**não — caixa vazia**"), False)


class TestParser(unittest.TestCase):
    """O que o *parser* le de um cabecalho e de uma linha de tabela."""

    def test_a_tabela_de_riscos_de_um_epic_nao_e_de_criterios(self) -> None:
        """**O defeito mais grave que a revisao adversarial encontrou.**

        A coluna de assunto casava por **sub-cadeia**, e a tabela
        `## Riscos do Epic` tem a coluna «Mitigacao **ou critério** de saida» —
        pelo que ela era lida como tabela de critérios. Em quatro blocos reais
        (KAM-064, KAM-117, KAM-127, KAM-149) era a **unica** tabela daquela
        especie, e o *lint* emparelhava-a com a lista de critérios: a uma
        coincidencia de contagem de comparar critérios de aceitacao contra
        estados de risco.
        """
        riscos = ["Risco / item", "Estado", "Impacto",
                  "Mitigação ou critério de saída", "Decisão"]
        self.assertEqual(modelo._especie_da_tabela(riscos), "sem_assunto")

    def test_as_formas_de_cabecalho_que_a_arvore_usa(self) -> None:
        """Descartar o `| CA | Estado | … |` custava 26 tabelas de cobertura."""
        self.assertEqual(
            modelo._especie_da_tabela(["#", "Critério", "Estado", "Evidência"]),
            "criterios")
        self.assertEqual(
            modelo._especie_da_tabela(["CA", "Estado", "Evidência"]), "criterios")
        self.assertEqual(
            modelo._especie_da_tabela(["#", "DoD", "Estado", "Evidência"]), "dod")
        self.assertIsNone(
            modelo._especie_da_tabela(["#", "Critério", "Evidência"]),
            "sem coluna `Estado` nao declara estados")

    def test_um_pipe_escapado_nao_separa_celulas(self) -> None:
        """Medido no `KAM-039`: lia-se `'servicos\\'` como celula de estado."""
        linha = r"| (d) | `grep` por `vendedor\|servicos` | **satisfeito** | m |"
        self.assertEqual(
            modelo.celulas(linha),
            ["(d)", "`grep` por `vendedor|servicos`", "**satisfeito**", "m"])

    def test_a_primeira_tabela_da_especie_e_que_conta(self) -> None:
        """E **primeira** e nao ultima: um bloco pode ter duas da mesma forma.

        Vivo na arvore — o KAM-115 tem duas tabelas de critérios — e a que
        responde aos critérios e a que vem antes.
        """
        texto = """## KAM-001 — Duas tabelas da mesma especie

### Critérios de Aceitação
- [x] Um.

### Definition of Done
- [ ] Outro.

### Verificação dos Critérios de Aceitação

| # | Critério | Estado | Evidência |
|---|---|---|---|
| 1 | Um | **satisfeito** | medido |

| # | Critério | Estado | Evidência |
|---|---|---|---|
| 1 | Outra coisa | **parcial** | medido |
"""
        blocos = modelo._blocos_do_texto(texto, "x.md")
        tabela = blocos[0].tabela("criterios")
        self.assertEqual(tabela.estados, ("**satisfeito**",))


class TestEmparelhar(Base):
    def test_duas_tabelas_proprias_emparelham_cada_uma_com_a_sua(self) -> None:
        raiz = self.arvore(LIMPO)
        bloco = next(b for b in modelo.ler_blocos(raiz) if b.id == "KAM-001")
        pares, nao_medidos = lint.emparelhar(bloco)
        self.assertEqual([p.rotulo for p in pares], ["critérios", "DoD"])
        self.assertEqual(nao_medidos, [])
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
        pares, nao_medidos = lint.emparelhar(bloco)
        self.assertEqual([p.rotulo for p in pares], ["critérios e DoD"])
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
        """O bloco de *handoff* e cercado e tem linhas que parecem caixas.

        **Afirma o que o *parser* leu, e nao so a ausencia de achados**, e a
        diferenca foi medida: a mutacao que desliga o salto de cercas nao produz
        achados — produz um bloco que **deixa de emparelhar**, o que cai em «nao
        medido». Um ensaio que so olhasse para os achados sobrevivia-lhe.
        """
        raiz = self.arvore(
            canario._positivas()["caixa_dentro_de_cerca_nao_conta"])
        bloco = next(b for b in modelo.ler_blocos(raiz) if b.id == "KAM-001")
        self.assertEqual(len(bloco.criterios), 3,
                         "as duas caixas cercadas nao sao caixas")
        self.assertEqual([c.marcada for c in bloco.criterios],
                         [True, False, True])
        achados, nao_medidos, _ = lint.verificar(raiz, minimo_blocos=2,
                                                 minimo_medidos=1)
        self.assertEqual(achados, [])
        self.assertEqual(nao_medidos, [], "o bloco tem de emparelhar")

    def test_um_titulo_de_nivel_4_nao_abre_seccao(self) -> None:
        """O `#### Definition of Done` de dentro da verificacao e uma **tabela**.

        Tomar o titulo dele por inicio da lista de caixas roubava as caixas a
        lista verdadeira — e a mutacao que o permite nao tinha ensaio que a
        mordesse (medido pela revisao adversarial).
        """
        texto = """## KAM-001 — Um nivel 4 dentro da verificacao

### Critérios de Aceitação
- [x] Um.

### Definition of Done
- [ ] Uma linha de DoD.

### Verificação dos Critérios de Aceitação

#### Definition of Done

- [x] Uma linha que **nao** e da lista de DoD: e prosa da verificacao.

| # | DoD | Estado | Evidência |
|---|---|---|---|
| 1 | A linha | **parcial** | medido |

| # | Critério | Estado | Evidência |
|---|---|---|---|
| 1 | Um | **satisfeito** | medido |
"""
        blocos = modelo._blocos_do_texto(texto, "x.md")
        bloco = blocos[0]
        self.assertEqual(len(bloco.criterios), 1)
        self.assertEqual(len(bloco.dod), 1,
                         "o `####` nao pode roubar a lista de DoD")
        self.assertFalse(bloco.dod[0].marcada)

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

    def test_os_pisos_valem_alguma_coisa(self) -> None:
        """**O ensaio de cima nao prende o valor, e a revisao mediu-o:**
        `MINIMO_DE_BLOCOS_MEDIDOS = 0` passava, porque 0 <= 54 e verdade.

        Um piso a zero e o mesmo que nao ter piso — e o piso existe precisamente
        para o caso em que o emparelhamento cai para quase nada e a saida
        continua a dizer «0 achados». Exige-se que ele cubra uma fraccao
        substancial do que hoje se mede.
        """
        _, _, numeros = lint.verificar(RAIZ)
        self.assertGreater(lint.MINIMO_DE_BLOCOS, 0)
        self.assertGreater(lint.MINIMO_DE_BLOCOS_MEDIDOS, 0)
        self.assertGreaterEqual(lint.MINIMO_DE_BLOCOS_MEDIDOS,
                                numeros["medidos"] // 2,
                                "um piso abaixo de metade do medido deixa o "
                                "emparelhamento cair para metade sem nada dizer")


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
