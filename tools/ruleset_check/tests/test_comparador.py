"""Normalizacao e comparacao sobre respostas de API em fixture (KAM-137).

O criterio 4 do ticket escreve a lista do que se compara, e esta suite segue-a a
letra: os sete contextos, `pull_request`, `deletion`, `non_fast_forward`,
`enforcement`, `bypass_actors` vazio, e os campos volateis ignorados **nomeados
um a um**. Mais o que o ticket pede nos testes unitarios: um campo de politica
ausente, e `bypass_actors` com uma entrada.
"""

from __future__ import annotations

import copy
import unittest

from ruleset_check import comparador

from .base import contextos, espelho, regra, resposta_da_api, VOLATEIS_NA_FIXTURE


def regras_de(divergencias) -> list[str]:
    return sorted(d.regra for d in divergencias)


class TestCasoD(unittest.TestCase):
    """(d) do criterio 3: ficheiro e API iguais -> verde."""

    def test_espelho_igual_a_api_nao_tem_divergencias(self) -> None:
        self.assertEqual(comparador.comparar(espelho(), resposta_da_api()), [])

    def test_a_ordem_das_regras_nao_e_politica(self) -> None:
        bruto = resposta_da_api()
        bruto["rules"] = list(reversed(bruto["rules"]))
        self.assertEqual(comparador.comparar(espelho(), bruto), [])

    def test_a_ordem_dos_contextos_nao_e_politica(self) -> None:
        bruto = resposta_da_api()
        contextos(bruto).reverse()
        self.assertEqual(comparador.comparar(espelho(), bruto), [])

    def test_a_ordem_de_include_e_exclude_nao_e_politica(self) -> None:
        local = espelho()
        local["conditions"]["ref_name"]["include"] = ["~DEFAULT_BRANCH", "refs/heads/x"]
        bruto = resposta_da_api()
        bruto["conditions"]["ref_name"]["include"] = ["refs/heads/x", "~DEFAULT_BRANCH"]
        self.assertEqual(comparador.comparar(local, bruto), [])


class TestVolateisIgnorados(unittest.TestCase):
    """Os campos que a API devolve e que nao sao politica, **um a um**."""

    def test_a_lista_da_fixture_e_a_do_comparador(self) -> None:
        """Se um volatil novo entrar no comparador sem entrar na fixture, nada o testa."""
        self.assertEqual(sorted(VOLATEIS_NA_FIXTURE), sorted(comparador.VOLATEIS))

    def test_cada_volatil_tem_a_razao_escrita(self) -> None:
        for nome, razao in comparador.VOLATEIS.items():
            with self.subTest(campo=nome):
                self.assertTrue(razao.strip(), f"{nome} esta na lista sem razao escrita")

    def test_cada_volatil_sozinho_nao_produz_divergencia(self) -> None:
        for nome, valor in VOLATEIS_NA_FIXTURE.items():
            with self.subTest(campo=nome):
                bruto = espelho()
                bruto[nome] = copy.deepcopy(valor)
                self.assertEqual(comparador.comparar(espelho(), bruto), [])

    def test_cada_volatil_mudar_de_valor_nao_produz_divergencia(self) -> None:
        for nome in VOLATEIS_NA_FIXTURE:
            with self.subTest(campo=nome):
                bruto = resposta_da_api(**{nome: "outro-valor-qualquer"})
                self.assertEqual(comparador.comparar(espelho(), bruto), [])

    def test_um_campo_de_topo_que_nao_esta_em_nenhuma_das_listas_falha(self) -> None:
        """Nao se deita fora em silencio: uma politica nova num campo novo e vermelha."""
        bruto = resposta_da_api(regra_nova_qualquer={"parameters": {}})
        self.assertEqual(regras_de(comparador.comparar(espelho(), bruto)), ["campo-novo-na-api"])

    def test_um_campo_a_mais_no_espelho_falha(self) -> None:
        local = espelho()
        local["coisa_que_ninguem_exporta"] = True
        self.assertEqual(
            regras_de(comparador.comparar(local, resposta_da_api())),
            ["campo-a-mais-no-espelho"],
        )


class TestCampoDePoliticaAusente(unittest.TestCase):
    """«Um campo de politica ausente» — o caso que a igualdade sozinha nao apanha."""

    def test_bypass_actors_ausente_na_api(self) -> None:
        bruto = resposta_da_api()
        del bruto["bypass_actors"]
        divergencias = comparador.comparar(espelho(), bruto)
        self.assertEqual(regras_de(divergencias), ["campo-de-politica-ausente"])
        self.assertIn("GitHub", divergencias[0].mensagem)

    def test_enforcement_ausente_nos_dois_lados_continua_a_ser_divergencia(self) -> None:
        """O caso que motiva a regra: ausente dos dois lados e igual a si proprio."""
        local = espelho()
        del local["enforcement"]
        bruto = resposta_da_api()
        del bruto["enforcement"]
        divergencias = comparador.comparar(local, bruto)
        self.assertEqual(regras_de(divergencias), ["campo-de-politica-ausente"])
        self.assertEqual(divergencias[0].onde, "enforcement")

    def test_cada_campo_de_topo_ausente_e_apanhado(self) -> None:
        for campo in comparador.CAMPOS_DE_TOPO:
            with self.subTest(campo=campo):
                bruto = resposta_da_api()
                del bruto[campo]
                self.assertIn(
                    "campo-de-politica-ausente",
                    regras_de(comparador.comparar(espelho(), bruto)),
                )

    def test_um_parametro_de_politica_ausente_e_apanhado(self) -> None:
        for tipo, parametros in comparador.PARAMETROS_DE_POLITICA.items():
            for parametro in parametros:
                with self.subTest(regra=tipo, parametro=parametro):
                    bruto = resposta_da_api()
                    del regra(bruto, tipo)["parameters"][parametro]
                    divergencias = comparador.comparar(espelho(), bruto)
                    self.assertIn("campo-de-politica-ausente", regras_de(divergencias))
                    self.assertIn(
                        f"rules.{tipo}.{parametro}", [d.onde for d in divergencias]
                    )

    def test_o_bloco_parameters_inteiro_ausente_e_apanhado(self) -> None:
        bruto = resposta_da_api()
        del regra(bruto, "pull_request")["parameters"]
        divergencias = comparador.comparar(espelho(), bruto)
        self.assertEqual(set(regras_de(divergencias)), {"campo-de-politica-ausente"})
        self.assertEqual(
            len(divergencias), len(comparador.PARAMETROS_DE_POLITICA["pull_request"])
        )


class TestBypassActors(unittest.TestCase):
    """(c) do criterio 3, e o criterio 4: a lista tem de estar vazia."""

    UMA_ENTRADA = [{"actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "always"}]

    def test_uma_entrada_no_github_e_vermelho(self) -> None:
        bruto = resposta_da_api(bypass_actors=self.UMA_ENTRADA)
        divergencias = comparador.comparar(espelho(), bruto)
        self.assertIn("bypass-actor-no-github", regras_de(divergencias))

    def test_uma_entrada_no_github_tambem_diverge_do_ficheiro(self) -> None:
        bruto = resposta_da_api(bypass_actors=self.UMA_ENTRADA)
        self.assertEqual(
            regras_de(comparador.comparar(espelho(), bruto)),
            ["bypass-actor-no-github", "campo-divergente"],
        )

    def test_por_o_actor_tambem_no_ficheiro_nao_apaga_o_vermelho(self) -> None:
        """O ficheiro nao e autoridade para conceder bypass.

        E a diferenca entre este campo e todos os outros: nos outros, igualar os
        dois lados e a reposicao da coerencia. Aqui, a unica saida verde e
        retirar o actor no GitHub.
        """
        local = espelho()
        local["bypass_actors"] = copy.deepcopy(self.UMA_ENTRADA)
        bruto = resposta_da_api(bypass_actors=copy.deepcopy(self.UMA_ENTRADA))
        self.assertEqual(
            regras_de(comparador.comparar(local, bruto)), ["bypass-actor-no-github"]
        )

    def test_a_mensagem_diz_quantos(self) -> None:
        dois = self.UMA_ENTRADA + [
            {"actor_id": 1, "actor_type": "Integration", "bypass_mode": "pull_request"}
        ]
        bruto = resposta_da_api(bypass_actors=dois)
        divergencia = [
            d for d in comparador.comparar(espelho(), bruto)
            if d.regra == "bypass-actor-no-github"
        ][0]
        self.assertIn("2 actor(es)", divergencia.mensagem)


class TestContextos(unittest.TestCase):
    """(a) e (b) do criterio 3, sobre fixture. Os dois sentidos, nomeados."""

    def test_um_required_check_retirado_no_github(self) -> None:
        """(a): esta no ficheiro e o GitHub nao o exige."""
        bruto = resposta_da_api()
        retirado = contextos(bruto).pop(2)["context"]
        divergencias = comparador.comparar(espelho(), bruto)
        self.assertEqual(regras_de(divergencias), ["contexto-so-no-ficheiro"])
        self.assertIn(retirado, divergencias[0].onde)

    def test_um_contexto_acrescentado_so_no_ficheiro(self) -> None:
        """(b): o ficheiro declara um contexto que o GitHub nao exige.

        E o mesmo sentido de (a) — o que muda e quem mexeu —, e a mensagem tem
        de dizer que um PR que o deixe vermelho funde na mesma.
        """
        local = espelho()
        for entrada in local["rules"]:
            if entrada["type"] == "required_status_checks":
                entrada["parameters"]["required_status_checks"].append(
                    {"context": "gate 3b — nomes canonicos"}
                )
        divergencias = comparador.comparar(local, resposta_da_api())
        self.assertEqual(regras_de(divergencias), ["contexto-so-no-ficheiro"])
        self.assertIn("funde na mesma", divergencias[0].mensagem)

    def test_um_contexto_acrescentado_so_no_github(self) -> None:
        bruto = resposta_da_api()
        contextos(bruto).append({"context": "gate 10 — SAST"})
        divergencias = comparador.comparar(espelho(), bruto)
        self.assertEqual(regras_de(divergencias), ["contexto-so-no-github"])
        self.assertIn("gate 10 — SAST", divergencias[0].onde)

    def test_os_sete_contextos_do_espelho(self) -> None:
        """A lista do criterio 4 diz «os sete contextos». Esta e a conta."""
        self.assertEqual(len(contextos(espelho())), 7)

    def test_o_integration_id_e_politica_e_nao_volatil(self) -> None:
        """Um contexto reportado por outra aplicacao nao e o mesmo contexto."""
        bruto = resposta_da_api()
        contextos(bruto)[0]["integration_id"] = 12345
        self.assertEqual(
            regras_de(comparador.comparar(espelho(), bruto)),
            ["contexto-so-no-ficheiro", "contexto-so-no-github"],
        )


class TestRegrasEParametros(unittest.TestCase):
    def test_deletion_retirada_no_github(self) -> None:
        bruto = resposta_da_api()
        bruto["rules"] = [r for r in bruto["rules"] if r["type"] != "deletion"]
        divergencias = comparador.comparar(espelho(), bruto)
        self.assertEqual(regras_de(divergencias), ["regra-ausente-no-github"])
        self.assertEqual(divergencias[0].onde, "rules.deletion")

    def test_non_fast_forward_retirada_no_github(self) -> None:
        bruto = resposta_da_api()
        bruto["rules"] = [r for r in bruto["rules"] if r["type"] != "non_fast_forward"]
        self.assertEqual(
            regras_de(comparador.comparar(espelho(), bruto)), ["regra-ausente-no-github"]
        )

    def test_uma_regra_que_o_github_aplica_e_o_ficheiro_nao_declara(self) -> None:
        bruto = resposta_da_api()
        bruto["rules"].append({"type": "creation"})
        self.assertEqual(
            regras_de(comparador.comparar(espelho(), bruto)), ["regra-nao-declarada"]
        )

    def test_uma_aprovacao_a_menos(self) -> None:
        bruto = resposta_da_api()
        regra(bruto, "pull_request")["parameters"]["required_approving_review_count"] = 1
        divergencias = comparador.comparar(espelho(), bruto)
        self.assertEqual(regras_de(divergencias), ["parametro-divergente"])
        self.assertEqual(
            divergencias[0].onde, "rules.pull_request.required_approving_review_count"
        )

    def test_strict_policy_comparado_como_esta_e_nao_como_devia_ser(self) -> None:
        """`false` e deliberado (README do ruleset). O comparador nao opina."""
        self.assertEqual(comparador.comparar(espelho(), resposta_da_api()), [])
        bruto = resposta_da_api()
        regra(bruto, "required_status_checks")["parameters"][
            "strict_required_status_checks_policy"
        ] = True
        self.assertEqual(
            regras_de(comparador.comparar(espelho(), bruto)), ["parametro-divergente"]
        )

    def test_um_parametro_novo_fora_da_lista_escrita_tambem_e_apanhado(self) -> None:
        """A lista e sobre o que nao pode faltar; a comparacao e pela uniao."""
        bruto = resposta_da_api()
        regra(bruto, "pull_request")["parameters"]["parametro_que_a_api_passou_a_dar"] = 3
        self.assertEqual(
            regras_de(comparador.comparar(espelho(), bruto)), ["parametro-divergente"]
        )

    def test_enforcement_desligado(self) -> None:
        bruto = resposta_da_api(enforcement="evaluate")
        divergencias = comparador.comparar(espelho(), bruto)
        self.assertEqual(regras_de(divergencias), ["campo-divergente"])
        self.assertEqual(divergencias[0].onde, "enforcement")

    def test_conditions_que_deixam_de_casar_main(self) -> None:
        bruto = resposta_da_api()
        bruto["conditions"]["ref_name"]["include"] = ["refs/heads/nunca-existe"]
        self.assertEqual(regras_de(comparador.comparar(espelho(), bruto)), ["campo-divergente"])

    def test_target_trocado_de_branch_para_tag(self) -> None:
        bruto = resposta_da_api(target="tag")
        self.assertEqual(regras_de(comparador.comparar(espelho(), bruto)), ["campo-divergente"])

    def test_nome_do_ruleset_trocado(self) -> None:
        bruto = resposta_da_api(name="outra coisa")
        self.assertEqual(regras_de(comparador.comparar(espelho(), bruto)), ["campo-divergente"])


class TestEspelhoIlegivel(unittest.TestCase):
    """Saida 2 e nao 1: um espelho malformado nao e uma divergencia de politica."""

    def test_rules_sem_type(self) -> None:
        bruto = resposta_da_api()
        bruto["rules"] = [{"parameters": {}}]
        with self.assertRaises(comparador.EspelhoInvalido):
            comparador.comparar(espelho(), bruto)

    def test_tipo_de_regra_repetido(self) -> None:
        bruto = resposta_da_api()
        bruto["rules"].append({"type": "deletion"})
        with self.assertRaises(comparador.EspelhoInvalido):
            comparador.comparar(espelho(), bruto)

    def test_bypass_actors_que_nao_e_lista(self) -> None:
        bruto = resposta_da_api(bypass_actors={"actor_id": 1})
        with self.assertRaises(comparador.EspelhoInvalido):
            comparador.comparar(espelho(), bruto)


class TestOEspelhoReal(unittest.TestCase):
    def test_tem_exactamente_os_campos_comparados(self) -> None:
        self.assertEqual(sorted(espelho()), sorted(comparador.CAMPOS_DE_TOPO))

    def test_tem_as_quatro_regras_com_parametros_declarados(self) -> None:
        tipos = {r["type"] for r in espelho()["rules"]}
        self.assertEqual(tipos, set(comparador.PARAMETROS_DE_POLITICA))

    def test_bypass_actors_esta_vazio(self) -> None:
        self.assertEqual(espelho()["bypass_actors"], [])

    def test_enforcement_esta_activo(self) -> None:
        self.assertEqual(espelho()["enforcement"], "active")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
