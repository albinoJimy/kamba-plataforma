"""O classificador de diferencas, par a par (KAM-007, criterio 3).

Oito pares, que sao os que os «Testes Requeridos» do bloco pedem, e dentro
deles os quatro casos do criterio 3 — «remover, renomear, mudar o tipo ou
tornar obrigatorio um campo» de um lado, «acrescentar campo opcional» do outro.

A pergunta que cada teste responde e sempre a mesma: **esta diferenca obriga a
`versao + 1`?** O §6.6 diz que sim para tudo o que seja remocao, mudanca de
tipo ou mudanca de significado, e nao para um campo novo opcional.
"""

from __future__ import annotations

import copy
import unittest

from contract_diff import diff


def schema(propriedades: dict, obrigatorios: list[str] | None = None) -> dict:
    """Um payload fechado, que e a forma de todos os contratos."""
    return {
        "type": "object",
        "additionalProperties": False,
        "required": obrigatorios or [],
        "properties": propriedades,
    }


BASE = schema(
    {
        "order_id": {"type": "string", "format": "uuid"},
        "valor_minor": {"type": "integer", "minimum": 0},
        "currency": {"type": "string", "enum": ["AOA"]},
        "motivo": {"type": "string"},
    },
    ["order_id", "valor_minor", "currency"],
)


def mudado(alteracao) -> dict:
    copia = copy.deepcopy(BASE)
    alteracao(copia)
    return copia


class TestQuebrante(unittest.TestCase):
    """Os quatro do criterio 3, mais os que o §6.6 cobre por «significado»."""

    def quebra(self, actual: dict) -> list[diff.Diferenca]:
        achados = diff.quebra(diff.comparar(BASE, actual))
        self.assertTrue(achados, "esta diferenca tinha de ser quebrante")
        return achados

    def test_remover_um_campo(self) -> None:
        def remover(d):
            del d["properties"]["motivo"]

        (achado,) = self.quebra(mudado(remover))
        self.assertIn("desapareceu", achado.porque)

    def test_renomear_um_campo(self) -> None:
        """Renomear le-se como remover mais acrescentar, e e o que se reporta.

        O classificador nao adivinha intencoes: ve um campo que saiu e um que
        entrou. O que importa e que o lado que **quebra** — a saida — aparece.
        """
        def renomear(d):
            d["properties"]["razao"] = d["properties"].pop("motivo")

        achados = self.quebra(mudado(renomear))
        self.assertEqual([a.caminho for a in achados], ["(raiz).motivo"])

    def test_mudar_o_tipo_de_um_campo(self) -> None:
        def mudar(d):
            d["properties"]["valor_minor"] = {"type": "string"}

        achados = self.quebra(mudado(mudar))
        self.assertTrue(any("o tipo mudou" in a.porque for a in achados))

    def test_tornar_um_campo_obrigatorio(self) -> None:
        def tornar(d):
            d["required"].append("motivo")

        (achado,) = self.quebra(mudado(tornar))
        self.assertIn("passou a obrigatorio", achado.porque)

    def test_um_campo_novo_obrigatorio(self) -> None:
        """Nao e aditivo: o produtor antigo nao o envia."""
        def acrescentar(d):
            d["properties"]["novo"] = {"type": "string"}
            d["required"].append("novo")

        (achado,) = self.quebra(mudado(acrescentar))
        self.assertIn("obrigatorio", achado.porque)

    def test_deixar_de_ser_obrigatorio(self) -> None:
        """Quem lia o campo sem verificar passa a ler nada."""
        def soltar(d):
            d["required"].remove("currency")

        (achado,) = self.quebra(mudado(soltar))
        self.assertIn("deixou de o ser", achado.porque)

    def test_acrescentar_um_valor_ao_enum(self) -> None:
        """Parece aditivo e nao e: um consumidor exaustivo nao sabe o que fazer."""
        def alargar(d):
            d["properties"]["currency"]["enum"] = ["AOA", "USD"]

        (achado,) = self.quebra(mudado(alargar))
        self.assertIn("ganhou", achado.porque)
        self.assertIn("exaustiva", achado.porque)

    def test_abrir_o_objecto(self) -> None:
        def abrir(d):
            d["additionalProperties"] = True

        (achado,) = self.quebra(mudado(abrir))
        self.assertIn("additionalProperties", achado.caminho)

    def test_uma_palavra_chave_desconhecida_conta_como_quebrante(self) -> None:
        """Falha fechada: o que o classificador nao le nao se aprova.

        A alternativa — «nao sei, deixa passar» — aprova exactamente as
        mudancas que ninguem previu, que sao as que precisam de olhos.
        """
        def inventar(d):
            d["oneOf"] = [{"type": "object"}]

        (achado,) = self.quebra(mudado(inventar))
        self.assertIn("falha fechada", achado.porque)


class TestAditivo(unittest.TestCase):
    def test_acrescentar_um_campo_opcional(self) -> None:
        """O unico caso que o §6.6 deixa passar na mesma versao."""
        def acrescentar(d):
            d["properties"]["nota_interna"] = {"type": "string"}

        achados = diff.comparar(BASE, mudado(acrescentar))
        self.assertEqual([a.classe for a in achados], [diff.ADITIVO])
        self.assertEqual(diff.quebra(achados), [])

    def test_mudar_a_prosa_nao_e_diferenca(self) -> None:
        def prosa(d):
            d["description"] = "outra coisa"
            d["properties"]["order_id"]["description"] = "o identificador"

        self.assertEqual(diff.comparar(BASE, mudado(prosa)), [])

    def test_identico_nao_da_diferenca_nenhuma(self) -> None:
        self.assertEqual(diff.comparar(BASE, copy.deepcopy(BASE)), [])


class TestAninhamento(unittest.TestCase):
    """As mesmas regras dentro de objectos e de listas, nao so a cabeca."""

    def test_dentro_de_um_objecto_aninhado(self) -> None:
        base = schema({"autenticacao": schema({"authn_ok": {"type": "boolean"}}, ["authn_ok"])},
                      ["autenticacao"])
        actual = copy.deepcopy(base)
        actual["properties"]["autenticacao"]["properties"]["authn_ok"] = {"type": "string"}
        achados = diff.quebra(diff.comparar(base, actual))
        self.assertEqual(len(achados), 1)
        self.assertEqual(achados[0].caminho, "(raiz).autenticacao.authn_ok")

    def test_dentro_dos_itens_de_uma_lista(self) -> None:
        base = schema({"linhas": {"type": "array", "items": schema({"sku": {"type": "string"}},
                                                                   ["sku"])}}, ["linhas"])
        actual = copy.deepcopy(base)
        del actual["properties"]["linhas"]["items"]["properties"]["sku"]
        (achado,) = diff.quebra(diff.comparar(base, actual))
        self.assertEqual(achado.caminho, "(raiz).linhas[].sku")
        # Uma so, e nao duas: o `required` dos itens continua a nomear o `sku`
        # nos dois lados, pelo que nao ha diferenca **nele**. O schema fica mal
        # formado — exige um campo que nao declara —, e isso e trabalho do
        # validador de exemplos, nao deste classificador.
        self.assertIn("desapareceu", achado.porque)


if __name__ == "__main__":
    unittest.main()
