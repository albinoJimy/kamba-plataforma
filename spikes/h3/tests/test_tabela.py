"""A tabela N1-N3, com as *fixtures* dos dois casos que o ticket nomeia.

«Testes unitarios do *script* de analise com *fixtures* (incluindo erro 2593109 e
sincronizacao > 24 h)». Os dois estao em `fixtures/n1_n3.jsonl`, e sao os dois
casos em que «nao medido» e «nao aconteceu» se confundem:

    N2   erro 2593109 — o dono recusou partilhar. Caso **normal** pela Meta,
         e so e exito de H3 se a recusa foi do dono (folha do operador)
    N3   26,5 h — **fora** do prazo duro de 24 h, e seguido de `PARTNER_REMOVED`

O que estes ensaios prendem, acima de tudo, e a regra do zero: **zero eventos de
um tipo escreve-se `NAO MEDIDO` e nunca `N`**. «Nao recebi o `FINISH`» e «nao
liguei o receptor a tempo» produzem os mesmos zero eventos e tem conclusoes
opostas — a primeira refuta H3 para aquele numero, a segunda nao diz nada.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tabela import (
    COLUNAS,
    COLUNAS_DA_FOLHA,
    FINISH,
    NAO_MEDIDO,
    PRAZO_DE_SINCRONIZACAO_S,
    ROTULOS,
    SEM_HISTORICO,
    RegistoInvalido,
    em_markdown,
    ler,
    medir,
)

RAIZ = Path(__file__).resolve().parents[1]
FIXTURE = RAIZ / "fixtures" / "n1_n3.jsonl"


class TestFixture(unittest.TestCase):
    def test_a_fixture_existe_e_tem_os_tres_numeros(self) -> None:
        self.assertTrue(FIXTURE.is_file(), f"{FIXTURE} em falta: corra fixtures/gerar.py")
        linhas = ler(FIXTURE)
        self.assertEqual({l["numero"] for l in linhas}, set(ROTULOS))

    def test_cada_linha_da_fixture_passa_a_allowlist(self) -> None:
        """A *fixture* nao pode conter o que o receptor nunca produziria."""
        from registo import validar

        for i, linha in enumerate(ler(FIXTURE), start=1):
            with self.subTest(linha=i):
                self.assertEqual(validar(linha), linha)

    def test_a_fixture_e_reproduzivel(self) -> None:
        """Regenerar da os mesmos bytes: o cenario esta no `gerar.py`, nao no disco."""
        antes = FIXTURE.read_bytes()
        resultado = subprocess.run(
            [sys.executable, str(RAIZ / "fixtures" / "gerar.py")],
            capture_output=True,
            text=True,
            # O proprio `gerar.py` poe a pasta do spike no `sys.path`; o
            # `kamba_core` vem do ambiente, que e o mesmo destes ensaios.
            env=None,
        )
        self.assertEqual(resultado.returncode, 0, resultado.stderr)
        self.assertEqual(FIXTURE.read_bytes(), antes, "a geracao nao e determinista")


class TestN1Nominal(unittest.TestCase):
    def setUp(self) -> None:
        self.medicao = medir(ler(FIXTURE))["N1"]

    def test_finish_recebido(self) -> None:
        self.assertEqual(self.medicao["finish"], "S")

    def test_historico_com_as_contagens(self) -> None:
        self.assertTrue(self.medicao["historico"].startswith("S —"))
        self.assertIn("214 mensagem", self.medicao["historico"])
        self.assertIn("20 conversa", self.medicao["historico"])

    def test_contactos(self) -> None:
        self.assertEqual(self.medicao["contactos"], "143")

    def test_sincronizacao_dentro_das_24h(self) -> None:
        self.assertIn("2.0 h", self.medicao["sincronizacao"])
        self.assertIn("< 24 h", self.medicao["sincronizacao"])

    def test_latencia_com_os_dez_envios_pedidos(self) -> None:
        """A mediana e o **n**: uma mediana de tres apresentada como dez e o
        defeito que esta coluna existe para nao ter."""
        self.assertIn("3.0 s", self.medicao["latencia_do_eco"])
        self.assertIn("n = 10", self.medicao["latencia_do_eco"])
        self.assertNotIn("menos de", self.medicao["latencia_do_eco"])


class TestN2SemHistorico(unittest.TestCase):
    """O erro 2593109, que e o primeiro dos dois casos do ticket."""

    def setUp(self) -> None:
        self.medicao = medir(ler(FIXTURE))["N2"]

    def test_o_codigo_aparece_na_celula(self) -> None:
        self.assertIn(str(SEM_HISTORICO), self.medicao["historico"])

    def test_nao_se_le_como_zero_mensagens_sem_razao(self) -> None:
        """A celula diz **porque** nao ha mensagens, e nao so que nao ha.

        «0 mensagens» e «o dono recusou partilhar» tem conclusoes opostas no
        limiar H3, e a celula tem de carregar a segunda.
        """
        self.assertIn("erro", self.medicao["historico"])
        self.assertNotEqual(self.medicao["historico"], "S — 0 mensagem(ns) em 0 conversa(s)")

    def test_a_latencia_declara_que_o_n_e_menor(self) -> None:
        self.assertIn("n = 1", self.medicao["latencia_do_eco"])
        self.assertIn("menos de", self.medicao["latencia_do_eco"])


class TestN3ForaDoPrazo(unittest.TestCase):
    """A sincronizacao > 24 h, que e o segundo caso do ticket."""

    def setUp(self) -> None:
        self.medicao = medir(ler(FIXTURE))["N3"]

    def test_a_celula_marca_o_excesso(self) -> None:
        self.assertIn("26.5 h", self.medicao["sincronizacao"])
        self.assertIn("> 24 h", self.medicao["sincronizacao"])

    def test_o_prazo_e_o_da_meta(self) -> None:
        self.assertEqual(PRAZO_DE_SINCRONIZACAO_S, 24 * 60 * 60)

    def test_sincronizacao_antes_do_finish_nao_se_le_como_cumprida(self) -> None:
        """Regressao: um negativo passava por prazo cumprido.

        Nao havia guarda de sinal, e `segundos <= 86400` da `True` para qualquer
        negativo: um `history` entregue **antes** do `FINISH` — e `E1` §5 diz que
        nao ha ordem garantida — imprimia `-1.0 h (< 24 h)`, um valor
        fisicamente impossivel com a marca de conformidade.
        """
        linhas = [
            {"tipo": "history", "numero": "N1",
             "recebido_em": "2026-11-10T07:00:00.000Z", "threads": 1, "mensagens": 1},
            {"tipo": "account_update", "numero": "N1",
             "recebido_em": "2026-11-10T08:00:00.000Z", "evento": FINISH},
        ]
        celula = medir(linhas)["N1"]["sincronizacao"]
        self.assertTrue(celula.startswith(NAO_MEDIDO), celula)
        self.assertIn("ANTES do FINISH", celula)
        self.assertNotIn("< 24 h", celula)

    def test_zero_ecos_e_nao_medido_e_nao_zero_segundos(self) -> None:
        """A regra do zero, no sitio onde um `0,0 s` parecia instantaneo."""
        self.assertTrue(self.medicao["latencia_do_eco"].startswith(NAO_MEDIDO))
        self.assertIn("0 ecos", self.medicao["latencia_do_eco"])

    def test_zero_ecos_tambem_nao_decide_o_eco_da_api(self) -> None:
        self.assertTrue(self.medicao["eco_da_api"].startswith(NAO_MEDIDO))

    def test_o_partner_removed_aparece_com_o_motivo(self) -> None:
        self.assertIn("PARTNER_REMOVED", self.medicao["account_update"])
        self.assertIn("PRIMARY_INACTIVITY", self.medicao["account_update"])


class TestRegraDoZero(unittest.TestCase):
    """Zero eventos nunca da `N`. A excepcao e o eco da API, que tem prova."""

    def test_um_registo_vazio_nao_da_nenhum_n(self) -> None:
        medicao = medir([])
        for rotulo in ROTULOS:
            for chave, _ in COLUNAS:
                with self.subTest(rotulo=rotulo, coluna=chave):
                    celula = medicao[rotulo][chave]
                    self.assertNotEqual(
                        celula, "N", "zero eventos nao prova ausencia (ver a nota)"
                    )

    def test_sem_finish_a_sincronizacao_nao_se_calcula(self) -> None:
        linhas = [
            {"tipo": "history", "numero": "N1", "recebido_em": "2026-11-10T08:00:00.000Z",
             "threads": 1, "mensagens": 1}
        ]
        celula = medir(linhas)["N1"]["sincronizacao"]
        self.assertTrue(celula.startswith(NAO_MEDIDO))
        self.assertIn("sem FINISH", celula)

    def test_nenhuma_coluna_escreve_n_sobre_zero_envios_nossos(self) -> None:
        """Regressao: a excepcao a regra do zero era ela propria um defeito.

        A primeira versao tratava «houve ecos e nenhum e nosso» como prova de
        ausencia. Nao e: so o seria se tivessemos enviado ≥ 1 mensagem pela API,
        e **nada nos JSON-lines diz que enviamos** — com o `nossos.txt` esquecido
        todos os ecos saem `false` e a celula afirmava «uma mensagem da API nao
        gera eco» sobre zero envios.
        """
        celula = medir(ler(FIXTURE))["N1"]["eco_da_api"]
        self.assertTrue(celula.startswith(NAO_MEDIDO), celula)
        self.assertIn("0 de 10", celula)
        self.assertIn("folha", celula, "a celula tem de dizer onde se fecha o N")

    def test_um_eco_nosso_da_s_medido(self) -> None:
        """O controlo: o `S` continua a afirmar-se quando se viu."""
        linhas = [
            {"tipo": "smb_message_echoes", "numero": "N1",
             "recebido_em": "2026-11-10T08:00:00.000Z", "carimbo": 1_794_643_200,
             "id": "m_" + "a" * 32, "direccao": "echo", "enviada_por_nos": True}
        ]
        celula = medir(linhas)["N1"]["eco_da_api"]
        self.assertTrue(celula.startswith("S "), celula)

    def test_as_colunas_da_folha_ficam_nao_medidas(self) -> None:
        """O script nao inventa a operadora nem a versao da app."""
        medicao = medir(ler(FIXTURE))
        for rotulo in ROTULOS:
            for chave in COLUNAS_DA_FOLHA:
                with self.subTest(rotulo=rotulo, coluna=chave):
                    self.assertTrue(medicao[rotulo][chave].startswith(NAO_MEDIDO))
                    self.assertIn("folha", medicao[rotulo][chave])


class TestColunas(unittest.TestCase):
    """A conta das colunas **conta-se**, e nao se cita.

    Regressao: a prosa do §2 do ficheiro de resultado dizia «sete das treze (…)
    cinco a mao» — 7+5 = 12 sobre uma tabela de 13 — e faltava-lhe a coluna que
    o criterio 4 exige, a entrega do SMS, que o gerador **nao tinha**. O operador
    perdia-a no momento em que regenerasse o §2 com este script.
    """

    def test_a_entrega_do_sms_e_uma_coluna(self) -> None:
        self.assertIn("sms", dict(COLUNAS))
        self.assertIn("sms", COLUNAS_DA_FOLHA)

    def test_as_duas_metades_fecham_o_total(self) -> None:
        chaves = [c for c, _ in COLUNAS]
        self.assertEqual(len(chaves), len(set(chaves)), "coluna repetida")
        dos_eventos = [c for c in chaves if c not in COLUNAS_DA_FOLHA]
        self.assertEqual(
            len(COLUNAS_DA_FOLHA) + len(dos_eventos),
            len(chaves),
            "as da folha mais as dos eventos tem de fechar o total",
        )
        # Os numeros que a prosa do ficheiro de resultado cita, presos aqui.
        self.assertEqual((len(dos_eventos), len(COLUNAS_DA_FOLHA), len(chaves)),
                         (8, 6, 14))

    def test_toda_a_coluna_da_folha_sai_medida_na_folha(self) -> None:
        for chave in COLUNAS_DA_FOLHA:
            with self.subTest(coluna=chave):
                self.assertIn(chave, dict(COLUNAS), "coluna da folha fora do esquema")

    def test_toda_a_coluna_do_esquema_e_produzida(self) -> None:
        """Uma coluna no esquema que o `medir` nao escreva saia em branco."""
        medicao = medir(ler(FIXTURE))
        for chave, _ in COLUNAS:
            with self.subTest(coluna=chave):
                self.assertIn(chave, medicao["N1"])

    def test_o_ficheiro_de_resultado_tem_as_mesmas_catorze_linhas(self) -> None:
        """A tabela do §2 do ficheiro de evidencia nao pode divergir do gerador.

        E a divergencia que custou a linha da **entrega do SMS**: o ficheiro
        tinha-a, o gerador nao, e o §2 manda regenerar a tabela com o gerador —
        pelo que o operador a perdia. Prende-se aqui, pelos titulos, porque
        nenhum linter ve uma tabela de Markdown contra uma tupla de Python.
        """
        documento = (
            RAIZ.parents[1]
            / "docs/tecnica/evidencia/validacao/H3_Coexistencia_244.md"
        ).read_text(encoding="utf-8")
        for _, titulo in COLUNAS:
            with self.subTest(coluna=titulo):
                self.assertIn(
                    f"| {titulo} |",
                    documento,
                    f"o §2 do ficheiro de resultado nao tem a linha {titulo!r}",
                )


class TestLeitura(unittest.TestCase):
    def test_uma_linha_ilegivel_levanta_e_nao_se_salta(self) -> None:
        """Saltar baixava uma contagem em silencio, e a contagem decide H3."""
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "mau.jsonl"
            caminho.write_text('{"tipo":"messages"}\nnao e json\n', encoding="utf-8")
            with self.assertRaises(RegistoInvalido):
                ler(caminho)

    def test_uma_linha_sem_rotulo_levanta(self) -> None:
        with self.assertRaises(RegistoInvalido):
            medir([{"tipo": "messages", "recebido_em": "2026-11-10T08:00:00.000Z"}])

    def test_um_rotulo_fora_dos_tres_levanta(self) -> None:
        with self.assertRaises(RegistoInvalido):
            medir([{"tipo": "messages", "numero": "N4"}])

    def test_linhas_em_branco_nao_contam(self) -> None:
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "ok.jsonl"
            caminho.write_text('\n{"tipo":"messages"}\n\n', encoding="utf-8")
            self.assertEqual(len(ler(caminho)), 1)


class TestMarkdown(unittest.TestCase):
    def test_tem_uma_linha_por_coluna_e_uma_celula_por_numero(self) -> None:
        texto = em_markdown(medir(ler(FIXTURE)))
        linhas = texto.splitlines()
        # Cabecalho + separador + uma linha por propriedade.
        self.assertEqual(len(linhas), 2 + len(COLUNAS))
        for linha in linhas[2:]:
            self.assertEqual(linha.count("|"), len(ROTULOS) + 2)

    def test_o_cabecalho_nomeia_os_tres_numeros(self) -> None:
        texto = em_markdown(medir(ler(FIXTURE)))
        for rotulo in ROTULOS:
            self.assertIn(rotulo, texto.splitlines()[0])

    def test_o_finish_e_o_evento_da_meta(self) -> None:
        self.assertEqual(FINISH, "FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING")

    def test_a_tabela_nao_leva_telefone_nem_texto_livre(self) -> None:
        """A mesma medicao por forma do `test_privacidade`, sobre a **saida**.

        A tabela e o artefacto que vai para o ficheiro de evidencia, pelo que a
        medicao repete-se aqui: o registo pode estar limpo e a renderizacao
        reintroduzir algo.
        """
        from tests.test_privacidade import telefones, wamids

        texto = em_markdown(medir(ler(FIXTURE)))
        self.assertEqual(telefones(texto), [])
        self.assertEqual(wamids(texto), [])


if __name__ == "__main__":
    unittest.main()
