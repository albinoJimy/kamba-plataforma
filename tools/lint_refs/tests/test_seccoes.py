"""As citacoes de seccao (`§N`) do gate 3 — gramatica, fronteira e canarios.

Os dois canarios do fim sao o passo que esta casa nao dispensa: um conjunto com
uma citacao errada **tem** de fazer o `check` sair 1, e o conjunto como esta
**tem** de o fazer sair 0. Sem os dois, a prova de que o portao morde vivia numa
afirmacao em prosa.
"""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from lint_refs import seccoes
from lint_refs.cli import main, verificar_seccoes
from lint_refs.cli import Excepcoes, _ficheiros_do_git

ROOT = Path(__file__).resolve().parents[3]

#: O documento em que as dez citacoes erradas do KAM-169 foram escritas.
TECNICA_10 = "docs/tecnica/10_Onboarding_Governanca.md"


def _resolvedor(*seguidos: str) -> seccoes.Resolvedor:
    return seccoes.Resolvedor(set(seguidos))


class TestNumerosDeSeccao(unittest.TestCase):
    def test_le_dois_tres_e_quatro_cardinais(self) -> None:
        texto = (
            "# Titulo\n"
            "## 1. Introducao\n"
            "### 1.2 Ambito\n"
            "#### 7.6.2 Fundo\n"
            "##### 9.9 demasiado fundo\n"
        )
        self.assertEqual(
            seccoes.numeros_de_seccao(texto), frozenset({"1", "1.2", "7.6.2"})
        )

    def test_o_ponto_depois_do_numero_e_opcional(self) -> None:
        """O conjunto escreve `## 4.` com ponto e `### 4.1` sem."""
        self.assertEqual(
            seccoes.numeros_de_seccao("## 4. Backlog\n### 4.1 Gama\n"),
            frozenset({"4", "4.1"}),
        )

    def test_um_documento_sem_titulos_numerados_da_vazio(self) -> None:
        """E o sinal de nao-enderecavel: `docs/isolamento.md` e um *stub*."""
        self.assertEqual(
            seccoes.numeros_de_seccao("# Isolamento\n\n## Porque esta separado\n"),
            frozenset(),
        )

    def test_le_o_titulo_que_leva_o_proprio_paragrafo(self) -> None:
        """`## §6 — Quando reverter` e como dois ADRs locais numeram.

        Sem o `§?` no padrao, o `docs/adr/ADR-L002` e o `ADR-L003` nao tinham
        titulo numerado nenhum e **o documento inteiro ficava inenderecavel** —
        o que escondia um `§5` quebrado citado de
        `libs/py-core/src/kamba_core/secrets/port.py`.
        """
        self.assertEqual(
            seccoes.numeros_de_seccao(
                "# ADR\n\n## Contexto\n\n## §6 — Quando reverter, e o que falta\n"
            ),
            frozenset({"6"}),
        )

    def test_os_adrs_locais_que_numeram_assim_ficam_enderecaveis(self) -> None:
        """Contra a arvore real, nao contra uma *fixture*."""
        for rel in (
            "docs/adr/ADR-L002-injeccao-de-segredos.md",
            "docs/adr/ADR-L003-verificacao-do-ruleset.md",
        ):
            with self.subTest(documento=rel):
                numeros = seccoes.numeros_de_seccao(
                    (ROOT / rel).read_text(encoding="utf-8")
                )
                self.assertIn("6", numeros)
                self.assertFalse(seccoes.resolve("5", numeros))


class TestResolveONumero(unittest.TestCase):
    def test_um_numero_de_titulo_resolve(self) -> None:
        self.assertTrue(seccoes.resolve("18", frozenset({"18", "20.1"})))

    def test_um_numero_que_nao_existe_nao_resolve(self) -> None:
        self.assertFalse(seccoes.resolve("99", frozenset({"18", "20.1"})))

    def test_a_seccao_contentor_resolve_pelo_prefixo(self) -> None:
        """`docs/exploracao/06` numera `### 3.1` sob um `## Camada 3` sem numero.

        Sem esta regra as duas citacoes para esse documento eram falsos
        positivos — e um portao com falsos positivos e um portao que alguem
        desliga.
        """
        self.assertTrue(seccoes.resolve("3", frozenset({"3.1", "3.2", "5.1"})))

    def test_o_prefixo_tem_de_ser_de_um_nivel_e_nao_de_um_digito(self) -> None:
        """`§1` nao resolve por causa de um `### 12.3`: o separador conta."""
        self.assertFalse(seccoes.resolve("1", frozenset({"12.3", "18"})))


class TestResolvedorDeDocumento(unittest.TestCase):
    def test_caminho_completo_relativo_a_pasta_do_citante(self) -> None:
        resolver = _resolvedor("docs/tecnica/10_Onboarding.md")
        self.assertEqual(
            resolver("../tecnica/10_Onboarding.md", "docs/adr/ADR-L006.md"),
            "docs/tecnica/10_Onboarding.md",
        )

    def test_caminho_completo_relativo_a_raiz(self) -> None:
        resolver = _resolvedor("specs/INDICE.md")
        self.assertEqual(resolver("specs/INDICE.md", "docs/ci.md"), "specs/INDICE.md")

    def test_caminho_truncado_ao_prefixo_numerico(self) -> None:
        """A forma em que as dez do KAM-169 foram escritas: `docs/tecnica/10`."""
        resolver = _resolvedor("docs/tecnica/10_Onboarding.md")
        self.assertEqual(
            resolver("docs/tecnica/10", "specs/INDICE.md"),
            "docs/tecnica/10_Onboarding.md",
        )

    def test_um_prefixo_ambiguo_nao_designa_nada(self) -> None:
        """`docs/tecnica/0` nao designa nenhum dos documentos que comecam por 0."""
        resolver = _resolvedor(
            "docs/tecnica/00_Arquitectura.md", "docs/tecnica/01_Canais.md"
        )
        self.assertIsNone(resolver("docs/tecnica/0", "specs/INDICE.md"))

    def test_o_prefixo_tem_de_acabar_numa_fronteira_do_nome(self) -> None:
        """`docs/tecnica/1` nao designa o `10_Onboarding`, nem que seja o unico.

        Quem escreve «doc 1» quer o `01_Canais`; resolver para o documento
        errado e pior do que nao resolver. O teste anterior usava uma *fixture*
        com um `11_*.md` que este repositorio **nao tem**, pelo que a proteccao
        era sintetica: contra a arvore real, `docs/tecnica/1` era o unico `1*` e
        resolvia em silencio.
        """
        resolver = _resolvedor("docs/tecnica/10_Onboarding.md")
        self.assertIsNone(resolver("docs/tecnica/1", "specs/INDICE.md"))
        self.assertEqual(
            resolver("docs/tecnica/10", "specs/INDICE.md"),
            "docs/tecnica/10_Onboarding.md",
        )

    def test_a_fronteira_aceita_as_tres_formas_da_casa(self) -> None:
        """`10_Onboarding…`, `05-estrategia…` e `concierge.md`."""
        resolver = _resolvedor(
            "docs/tecnica/10_Onboarding.md",
            "docs/exploracao/05-estrategia.md",
            "docs/concierge.md",
        )
        for designador, esperado in (
            ("docs/tecnica/10", "docs/tecnica/10_Onboarding.md"),
            ("docs/exploracao/05", "docs/exploracao/05-estrategia.md"),
            ("docs/concierge", "docs/concierge.md"),
        ):
            with self.subTest(designador=designador):
                self.assertEqual(resolver(designador, "specs/INDICE.md"), esperado)

    def test_um_designador_sem_pasta_nao_e_enderecavel(self) -> None:
        """O cuneo abreviado do conjunto — `` `00` §12 `` — e ambiguo.

        Resolveria para `docs/tecnica/00`, `specs/00_KAMBA_Carta.md` ou
        `specs/00_System_Spec.md` conforme quem le, e so um mapa de apelidos
        escrito a mao decidiria. Fica fora do portao, de proposito.
        """
        resolver = _resolvedor("docs/tecnica/00_Arquitectura.md")
        self.assertIsNone(resolver("00", "docs/tecnica/10_Onboarding.md"))

    def test_um_documento_fora_do_conjunto_nao_resolve(self) -> None:
        resolver = _resolvedor("specs/INDICE.md")
        self.assertIsNone(resolver("docs/inexistente/99_Nada.md", "README.md"))

    def test_nao_sai_da_raiz(self) -> None:
        resolver = _resolvedor("specs/INDICE.md")
        self.assertIsNone(resolver("../../etc/passwd", "specs/INDICE.md"))


class TestGramaticaDasCitacoes(unittest.TestCase):
    def setUp(self) -> None:
        self.resolver = _resolvedor("docs/tecnica/10_Onboarding.md", "specs/INDICE.md")

    def _secs(self, linha: str, citante: str = "specs/EPIC-01.md") -> list[str]:
        return [c.seccao for c in seccoes.citacoes(linha, citante, self.resolver)]

    def test_ordem_a_documento_antes_do_paragrafo(self) -> None:
        self.assertEqual(self._secs("ver `specs/INDICE.md` §4 para o backlog"), ["4"])

    def test_ordem_b_paragrafo_antes_do_documento(self) -> None:
        """A forma do escape: «a linha de risco do §12 do `docs/tecnica/10`»."""
        self.assertEqual(
            self._secs("a linha de risco do §18 do `docs/tecnica/10`"), ["18"]
        )

    def test_a_corrida_de_paragrafos_pertence_ao_mesmo_documento(self) -> None:
        """`` `10` (§4, §8.5 e §9) `` — sem isto perdia-se tudo menos o primeiro."""
        self.assertEqual(
            self._secs("`docs/tecnica/10_Onboarding.md` (§4, §8.5, §9 e §20.1)"),
            ["4", "8.5", "9", "20.1"],
        )

    def test_a_ordem_b_ganha_a_ordem_a_sobre_o_mesmo_paragrafo(self) -> None:
        """«`X` §N do `Y`» e uma citacao de `Y`, nao de `X`.

        As duas ordens casam o mesmo `§` e dao documentos diferentes. «do»
        nomeia o documento; a ordem A so tem a vizinhanca. Sem a precedencia, o
        gate acusava a seccao no documento errado — e o bloco do KAM-170
        escreve exactamente essa frase.
        """
        citacoes = seccoes.citacoes(
            "o `specs/INDICE.md` §4 do `docs/tecnica/10_Onboarding.md`",
            "specs/EPIC-01.md",
            self.resolver,
        )
        self.assertEqual(
            [(c.destino, c.seccao) for c in citacoes],
            [("docs/tecnica/10_Onboarding.md", "4")],
        )

    def test_a_preposicao_locativa_nao_atribui_o_paragrafo(self) -> None:
        """«§N **em** `Y`» nao e uma citacao de `Y`: o `§` e de outro documento.

        «a regra do `docs/tecnica/09` §5.3 **em** `…/Alojamento_Cotacoes.md`»
        cita o §5.3 **do 09**, escrito **no** Alojamento_Cotacoes. Com `em` na
        ordem B, o gate atribuia-o ao segundo documento e acusava um §5.3 que
        ele nao tem — falso positivo sobre prosa valida.
        """
        citacoes = seccoes.citacoes(
            "a regra do `docs/tecnica/10_Onboarding.md` §4 em `specs/INDICE.md`",
            "specs/EPIC-01.md",
            self.resolver,
        )
        self.assertEqual(
            [(c.destino, c.seccao) for c in citacoes],
            [("docs/tecnica/10_Onboarding.md", "4")],
        )

    def test_a_corrida_aceita_o_travessao(self) -> None:
        """«§8.3–§8.4» expande as **pontas escritas**, nao o interior."""
        self.assertEqual(
            self._secs("`specs/INDICE.md` §4–§7"), ["4", "7"]
        )

    def test_uma_citacao_partida_por_mudanca_de_linha(self) -> None:
        """O designador fecha uma linha e o `§` abre a seguinte.

        Com a prosa a mudar de linha a ~80 colunas, e forma corrente — e
        deixava passar a gemea exacta de uma citacao corrigida neste ticket
        (`specs/EPIC-03_Agent_Runtime_Verticais.md:391-392`).
        """
        texto = "E o `docs/tecnica/10_Onboarding.md`\n§4 diz que sim.\n"
        citacoes = seccoes.citacoes(texto, "specs/EPIC-01.md", self.resolver)
        self.assertEqual(
            [(c.linha, c.destino, c.seccao) for c in citacoes],
            [(2, "docs/tecnica/10_Onboarding.md", "4")],
        )

    def test_a_fronteira_nao_atravessa_uma_linha_vazia(self) -> None:
        """Uma linha vazia separa paragrafos, e juntar atraves dela emparelhava
        um documento de um paragrafo com um `§` do seguinte."""
        texto = "fim do paragrafo com `docs/tecnica/10_Onboarding.md`\n\n§4 abre outro.\n"
        self.assertEqual(self._secs(texto), [])

    def test_um_paragrafo_nu_nao_e_enderecavel(self) -> None:
        """«o §8» dentro do proprio documento nao nomeia documento nenhum."""
        self.assertEqual(self._secs("como se ve no §8 acima"), [])

    def test_a_mesma_citacao_duas_vezes_na_linha_conta_uma(self) -> None:
        self.assertEqual(
            self._secs("`specs/INDICE.md` §4 e outra vez `specs/INDICE.md` §4"), ["4"]
        )

    def test_um_bloco_de_codigo_cercado_nao_conta(self) -> None:
        texto = (
            "antes\n"
            "```text\n"
            "NAO apagues a linha do §99 do `docs/tecnica/10`\n"
            "```\n"
            "depois\n"
        )
        self.assertEqual(self._secs(texto), [])

    def test_cercas_impares_varrem_tudo(self) -> None:
        """Mesma reserva do `scan.py`: uma cerca aberta nao cega o ficheiro.

        Um `.md` com cercas desequilibradas produz isto por acidente, e perder
        o varrimento dali para a frente e o lado errado em que perder.
        """
        texto = "```text\nver `specs/INDICE.md` §4\n"
        self.assertEqual(self._secs(texto), ["4"])

    def test_um_texto_sem_paragrafo_nenhum_nao_e_percorrido(self) -> None:
        self.assertEqual(self._secs("`specs/INDICE.md` linha 4"), [])


class TestBlocosDeHandoff(unittest.TestCase):
    """O bloco de *handoff* e cercado, e e o unico sitio onde um `§` da uma ordem.

    A condicao 3 saltava-os todos — e a ocorrencia que motivou este portao vivia
    exactamente ali: «NAO apagues a linha de risco do §12», dentro da cerca de
    `specs/tickets/KAM-169.md`. Um portao que nomeia o bloco de *handoff* como o
    caso que o motiva e nao o le promete o que nao faz.
    """

    BLOCO = (
        "## KAM-999 — exemplo\n"
        "\n"
        "### Handoff para Claude Code\n"
        "\n"
        "```text\n"
        "NAO apagues a linha de risco do §99 do `docs/tecnica/10_Onboarding.md`.\n"
        "```\n"
    )

    def setUp(self) -> None:
        self.resolver = _resolvedor("docs/tecnica/10_Onboarding.md")

    def test_dentro_de_um_bloco_de_handoff_varre_se(self) -> None:
        no_handoff = seccoes.linhas_de_handoff(self.BLOCO)
        citacoes = seccoes.citacoes(
            self.BLOCO, "specs/tickets/KAM-999.md", self.resolver, no_handoff
        )
        self.assertEqual([c.seccao for c in citacoes], ["99"])

    def test_sem_as_linhas_do_handoff_a_cerca_esconde_a_citacao(self) -> None:
        """O controlo: e a cerca que a escondia, e nao outra coisa."""
        citacoes = seccoes.citacoes(
            self.BLOCO, "specs/tickets/KAM-999.md", self.resolver
        )
        self.assertEqual(citacoes, [])

    def test_um_bloco_de_codigo_comum_continua_fora(self) -> None:
        """Alargar ao *handoff* nao alarga a todas as cercas."""
        texto = (
            "## 1. Exemplo\n"
            "\n"
            "```python\n"
            "# ver o §99 do `docs/tecnica/10_Onboarding.md`\n"
            "```\n"
        )
        no_handoff = seccoes.linhas_de_handoff(texto)
        self.assertEqual(no_handoff, frozenset())
        self.assertEqual(
            seccoes.citacoes(texto, "specs/EPIC-01.md", self.resolver, no_handoff), []
        )

    def test_a_arvore_tem_blocos_de_handoff_e_eles_sao_varridos(self) -> None:
        """Se a deteccao se partir, isto apanha-o: sao 170 blocos em 65 ficheiros."""
        total = 0
        for rel in ROOT.glob("specs/tickets/*.md"):
            total += len(seccoes.linhas_de_handoff(rel.read_text(encoding="utf-8")))
        self.assertGreater(total, 500, "os blocos de handoff deixaram de ser vistos")


class TestTokenDeDispensa(unittest.TestCase):
    def test_o_token_leva_a_seccao_e_o_destino(self) -> None:
        """O mesmo `§7.14` esta certo num documento e errado noutro."""
        citacao = seccoes.Citacao(1, "../docs/logs.md", "docs/logs.md", "7.14", "ctx")
        self.assertEqual(seccoes.token(citacao), "§7.14@docs/logs.md")


class TestOEscapeDoKam169(unittest.TestCase):
    """O que o portao apanha, e o que nao apanha, contra a arvore real.

    Nao e um teste de regressao do KAM-169: as dez citacoes ja foram corrigidas
    no PR #94. E a fronteira do portao, fixada para ninguem a supor mais larga
    do que e.
    """

    def setUp(self) -> None:
        self.numeros = seccoes.numeros_de_seccao(
            (ROOT / TECNICA_10).read_text(encoding="utf-8")
        )

    def test_os_destinos_certos_existem(self) -> None:
        """§18 e «Riscos e mitigacoes»; §20.1 e «Propostas de ADR»."""
        self.assertTrue(seccoes.resolve("18", self.numeros))
        self.assertTrue(seccoes.resolve("20.1", self.numeros))

    def test_uma_seccao_inventada_nao_resolve(self) -> None:
        self.assertFalse(seccoes.resolve("99", self.numeros))

    def test_a_sub_classe_que_este_portao_nao_fecha(self) -> None:
        """**O §12 e o §16 existem** — e por isso resolvem e passam.

        As dez do KAM-169 citavam seccoes que existem e eram as erradas
        («Segmento A vs B» em vez de «Riscos e mitigacoes»). Esse defeito e
        semantico: exige saber o que o texto afirma, e nenhuma maquina o decide.
        Este teste existe para que o limite esteja escrito num sitio que falha
        se alguem o apagar, e nao so numa frase do `seccoes.py`.
        """
        self.assertTrue(seccoes.resolve("12", self.numeros))
        self.assertTrue(seccoes.resolve("16", self.numeros))


def _conjunto_minimo(raiz: Path, citacao: str) -> None:
    """Um repositorio com o minimo que o gate 3 le, mais uma citacao de seccao.

    Os ficheiros sao **adicionados ao git**: o `lint_refs` varre `git ls-files`,
    e um ficheiro nao versionado da um verde que nao cobriu nada.
    """
    (raiz / "specs").mkdir(parents=True)
    (raiz / "docs" / "tecnica").mkdir(parents=True)
    (raiz / "ci").mkdir(parents=True)

    (raiz / "specs" / "INDICE.md").write_text(
        "# Indice\n\n## 4. Backlog mestre\n\n| ID | Titulo |\n|---|---|\n"
        "| KAM-001 | Um |\n\n## 5. Fim\n",
        encoding="utf-8",
    )
    (raiz / "docs" / "tecnica" / "00_Arquitectura_Solucao.md").write_text(
        "# Arquitectura\n\n"
        "## 8. Decisões de arquitectura\n\n| ID | Decisao |\n|---|---|\n"
        "| ADR-001 | Uma |\n\n"
        "## 12. Segmento A vs B\n\nOutra coisa.\n\n"
        "## 13. Decisoes\n\n### 13.3 Decisoes abertas\n\n| ID | Decisao |\n|---|---|\n"
        "| D1 | Uma |\n\n"
        "## 14. Fim\n\n"
        "## 18. Riscos e mitigações\n\nA linha de risco vive aqui.\n",
        encoding="utf-8",
    )
    (raiz / "ci" / "refs-allow.yaml").write_text(
        "version: 1\nplaceholders: []\nareas: []\nexcepcoes: []\n", encoding="utf-8"
    )
    (raiz / "specs" / "EPIC-01_Fundacoes_Dados.md").write_text(
        f"# Epic 1\n\n## 1. Contexto\n\n{citacao}\n", encoding="utf-8"
    )

    for argumentos in (["init", "-q"], ["add", "-A"]):
        subprocess.run(["git", *argumentos], cwd=raiz, check=True, capture_output=True)


class TestCanarios(unittest.TestCase):
    """A prova de que o portao morde, e de que nao morde o que esta certo."""

    def test_o_canario_de_citacao_errada_faz_o_check_sair_1(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            _conjunto_minimo(
                raiz, "A linha de risco do §99 do `docs/tecnica/00`, que nao existe."
            )
            self.assertEqual(main(["--root", str(raiz), "check"]), 1)

            achados, _ = verificar_seccoes(
                raiz, _ficheiros_do_git(raiz), Excepcoes.ler(raiz)
            )
            self.assertEqual(len(achados), 1, achados)
            self.assertIn("§99 nao existe", achados[0])
            self.assertIn("00_Arquitectura_Solucao.md", achados[0])
            self.assertIn("grep -nE", achados[0])

    def test_o_mesmo_canario_com_a_seccao_certa_sai_0(self) -> None:
        """O controlo negativo: prova que o 1 veio da citacao e nao da fixture."""
        with tempfile.TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            _conjunto_minimo(
                raiz, "A linha de risco do §18 do `docs/tecnica/00`, que existe."
            )
            self.assertEqual(main(["--root", str(raiz), "check"]), 0)

    def test_o_conjunto_como_esta_faz_o_check_sair_0(self) -> None:
        self.assertEqual(main(["--root", str(ROOT), "check"]), 0)

    def test_o_conjunto_nao_precisa_de_uma_unica_dispensa_de_seccao(self) -> None:
        """Uma verificacao que precisa de dispensas para passar e uma nota.

        As nove citacoes que a `main` tinha foram **corrigidas**, nao
        dispensadas: nenhuma entrada de `ci/refs-allow.yaml` tem a forma
        `§N@destino`.
        """
        excepcoes = Excepcoes.ler(ROOT)
        tokens = {
            token
            for conjunto in excepcoes.por_ficheiro.values()
            for token in conjunto
        } | excepcoes.placeholders
        self.assertEqual([t for t in tokens if t.startswith("§")], [])

    def test_o_varrimento_cobre_uma_quantidade_plausivel(self) -> None:
        """Se encolher de repente, alguem quebrou a descoberta."""
        _, estatisticas = verificar_seccoes(
            ROOT, _ficheiros_do_git(ROOT), Excepcoes.ler(ROOT)
        )
        self.assertGreater(estatisticas["enderecaveis"], 2000)
        self.assertGreater(estatisticas["varridos"], 100)

    def test_os_registos_datados_ficam_fora_do_varrimento(self) -> None:
        """Uma analise diz o que estava errado no dia em que foi escrita."""
        self.assertEqual(
            seccoes.EXCLUIDOS, ("docs/analises/", "docs/evidencia/")
        )


if __name__ == "__main__":
    unittest.main()
