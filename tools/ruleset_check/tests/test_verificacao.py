"""Um alvo de cada vez: resolver, ler, comparar (KAM-137).

Esta suite nasceu do bloqueador da revisao adversarial: com um alvo so, a
verificacao corrida de um clone do `albinoJimy/kamba-plataforma` lia o ruleset
do **privado**, imprimia «conforme» e saia 0 — dentro de um repositorio que nao
tinha ruleset nenhum.

O que se exige aqui, e que nao existia antes:

* um repositorio **sem rulesets** da **1** e nao 0, e nao 2: a leitura correu, e
  a resposta foi que a politica nao esta aplicada ali;
* um repositorio com rulesets mas **nenhum com o nome do espelho** da 1;
* o `id` resolve-se pelo nome, e um `id` declarado que nao bate e divergencia —
  um ruleset apagado e feito de novo tem nome igual e `id` diferente.
"""

from __future__ import annotations

import unittest
from unittest import mock

from ruleset_check import api, comparador, verificacao
from ruleset_check.config import Alvo

from .base import (
    ID_DO_PRIVADO, PRIVADO, PUBLICO, ROOT, api_falsa, entrada_da_listagem,
    espelho, resposta_da_api,
)

ALVO = Alvo(repositorio=PRIVADO, espelho=".github/rulesets/main.json",
            ruleset_id=ID_DO_PRIVADO, razao="o privado")
ALVO_SEM_ID = Alvo(repositorio=PUBLICO, espelho=".github/rulesets/main.json")


def correr(alvo: Alvo, mapa: dict) -> verificacao.Resultado:
    listar, obter = api_falsa(mapa)
    with mock.patch.object(api, "listar", listar), mock.patch.object(api, "obter", obter):
        return verificacao.verificar(ROOT, alvo, "gh")


def regras(resultado: verificacao.Resultado) -> list[str]:
    return sorted(d.regra for d in resultado.divergencias)


class TestResolucaoPeloNome(unittest.TestCase):
    def test_conforme(self) -> None:
        resultado = correr(ALVO, {PRIVADO: ([entrada_da_listagem()],
                                            {ID_DO_PRIVADO: resposta_da_api()})})
        self.assertTrue(resultado.conforme)
        self.assertEqual(resultado.ruleset_id, ID_DO_PRIVADO)
        self.assertEqual(resultado.contextos_no_espelho, 7)

    def test_resolve_sem_id_declarado_e_diz_qual_encontrou(self) -> None:
        resultado = correr(ALVO_SEM_ID, {PUBLICO: ([entrada_da_listagem(ruleset_id=7)],
                                                   {7: resposta_da_api()})})
        self.assertTrue(resultado.conforme)
        self.assertEqual(resultado.ruleset_id, 7)

    def test_escolhe_o_ruleset_certo_entre_varios(self) -> None:
        mapa = {PRIVADO: (
            [entrada_da_listagem(ruleset_id=1, nome="outro"),
             entrada_da_listagem(),
             entrada_da_listagem(ruleset_id=2, nome="tags")],
            {ID_DO_PRIVADO: resposta_da_api()},
        )}
        resultado = correr(ALVO, mapa)
        self.assertTrue(resultado.conforme)
        self.assertEqual(resultado.rulesets_no_repositorio, 3)


class TestRepositorioSemProteccao(unittest.TestCase):
    """O bloqueador, em forma de teste."""

    def test_repositorio_sem_ruleset_nenhum_e_vermelho(self) -> None:
        resultado = correr(ALVO_SEM_ID, {PUBLICO: ([], {})})
        self.assertFalse(resultado.conforme)
        self.assertEqual(regras(resultado), ["repositorio-sem-ruleset"])
        self.assertIsNone(resultado.ruleset_id)

    def test_a_mensagem_diz_o_que_falta_e_nao_so_que_falta(self) -> None:
        resultado = correr(ALVO_SEM_ID, {PUBLICO: ([], {})})
        mensagem = resultado.divergencias[0].mensagem
        for frase in ("PR obrigatorio", "required checks", "apagado ou reescrito"):
            self.assertIn(frase, mensagem)

    def test_nao_le_o_ruleset_de_outro_repositorio(self) -> None:
        """A raiz do defeito: o espelho descreve um ruleset que vive noutro sitio.

        Com o privado conforme e o publico vazio, o alvo do publico tem de dar
        vermelho — e nao herdar o verde do vizinho.
        """
        mapa = {PRIVADO: ([entrada_da_listagem()], {ID_DO_PRIVADO: resposta_da_api()}),
                PUBLICO: ([], {})}
        self.assertTrue(correr(ALVO, mapa).conforme)
        self.assertFalse(correr(ALVO_SEM_ID, mapa).conforme)

    def test_rulesets_a_mais_mas_nenhum_com_o_nome_do_espelho(self) -> None:
        mapa = {PUBLICO: ([entrada_da_listagem(ruleset_id=3, nome="tags protegidas")], {})}
        resultado = correr(ALVO_SEM_ID, mapa)
        self.assertEqual(regras(resultado), ["ruleset-ausente"])
        self.assertIn("tags protegidas", str(resultado.divergencias[0]))

    def test_dois_rulesets_com_o_mesmo_nome(self) -> None:
        mapa = {PUBLICO: ([entrada_da_listagem(ruleset_id=3),
                           entrada_da_listagem(ruleset_id=4)], {})}
        self.assertEqual(regras(correr(ALVO_SEM_ID, mapa)), ["ruleset-ambiguo"])


class TestIdDeclarado(unittest.TestCase):
    def test_id_que_nao_bate_e_divergencia(self) -> None:
        mapa = {PRIVADO: ([entrada_da_listagem(ruleset_id=555)],
                          {555: resposta_da_api()})}
        resultado = correr(ALVO, mapa)
        self.assertEqual(regras(resultado), ["id-do-ruleset-divergente"])
        self.assertIn("apagado e feito de novo", resultado.divergencias[0].mensagem)

    def test_id_que_nao_bate_nao_impede_a_comparacao_do_resto(self) -> None:
        mapa = {PRIVADO: ([entrada_da_listagem(ruleset_id=555)],
                          {555: resposta_da_api(enforcement="evaluate")})}
        self.assertEqual(
            regras(correr(ALVO, mapa)), ["campo-divergente", "id-do-ruleset-divergente"]
        )


class TestFalhasQueSaoDois(unittest.TestCase):
    """O que **nao** e divergencia: nao conseguir ler."""

    def test_listagem_que_nao_responde_propaga(self) -> None:
        with mock.patch.object(api, "listar", side_effect=api.ApiIndisponivel("403")):
            with self.assertRaises(api.ApiIndisponivel):
                verificacao.verificar(ROOT, ALVO, "gh")

    def test_espelho_sem_nome_e_erro_de_configuracao(self) -> None:
        sem_nome = espelho()
        del sem_nome["name"]
        with mock.patch.object(comparador, "ler_espelho", return_value=sem_nome):
            with self.assertRaises(comparador.EspelhoInvalido) as caixa:
                verificacao.verificar(ROOT, ALVO, "gh")
        self.assertIn("`name`", str(caixa.exception))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
