"""O catalogo gerado, do lado do Python (KAM-007).

O espelho do `packages/contracts/tests/eventos.test.ts`: o mesmo catalogo, o
mesmo confronto com os ficheiros no disco, do lado de quem escreve consumidores
em Python. Os dois existem porque o `contratos.py` e o `eventos.gerado.ts` saem
do mesmo gerador e podem divergir por um defeito **nele** — e um gerador com um
defeito escreve os dois ficheiros errados de forma coerente, que e precisamente
o que nenhum dos dois apanharia sozinho se comparassem um com o outro. Por isso
ambos comparam com **os contratos**, que sao a fonte.

E carrega-lo tem um segundo efeito, igual ao do lado TypeScript: um modulo em
`libs/*/src/**` que nenhum teste importa entra na medicao de cobertura a 0% das
suas linhas. Trezentas linhas geradas e nunca lidas baixavam o estrato sem nada
estar errado.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from kamba_core.eventos.contratos import CATALOGO

RAIZ = Path(__file__).resolve().parents[3]
CONTRATOS = RAIZ / "contratos" / "eventos"

#: Os trinta e oito do dicionario §3.5, emenda 1.11.
ESPERADOS = 38

#: Os sete do `docs/tecnica/06` §7.3.
PROIBIDOS = ("telefone", "msisdn", "bsuid", "nome", "morada", "texto", "email")


def payload_de(tipo: str) -> dict:
    documento = json.loads((CONTRATOS / tipo / "v1.schema.json").read_text(encoding="utf-8"))
    return documento["properties"]["payload"]


class TestCatalogoGerado(unittest.TestCase):
    def test_tem_um_tipo_por_contrato(self) -> None:
        na_pasta = sorted(p.name for p in CONTRATOS.iterdir() if p.is_dir())
        self.assertEqual(len(na_pasta), ESPERADOS)
        self.assertEqual(sorted(CATALOGO), na_pasta)

    def test_cada_entrada_diz_a_versao_do_ficheiro(self) -> None:
        for tipo, entrada in CATALOGO.items():
            with self.subTest(tipo=tipo):
                self.assertEqual(entrada["versao"], 1)

    def test_os_obrigatorios_e_os_permitidos_sao_os_do_schema(self) -> None:
        for tipo, entrada in CATALOGO.items():
            with self.subTest(tipo=tipo):
                payload = payload_de(tipo)
                self.assertEqual(
                    sorted(entrada["obrigatorios"]), sorted(payload.get("required") or [])
                )
                self.assertEqual(
                    sorted(entrada["permitidos"]), sorted(payload.get("properties") or {})
                )

    def test_todo_o_obrigatorio_e_permitido(self) -> None:
        """Um `required` sobre um campo nao declarado e um schema impossivel."""
        for tipo, entrada in CATALOGO.items():
            with self.subTest(tipo=tipo):
                self.assertLessEqual(
                    set(entrada["obrigatorios"]), set(entrada["permitidos"])
                )

    def test_nenhum_campo_tem_nome_de_dado_pessoal(self) -> None:
        """O terceiro caminho ate a mesma regra do §7.3.

        Os outros dois sao o `tools/contract_diff/pii.py` e a bateria do
        `packages/contracts`. Tres caminhos independentes, porque o dia em que
        um deles se desligar os outros continuam a gritar — e a regra que
        protegem e «nenhum dado pessoal directo sai num evento».
        """
        import re

        for tipo, entrada in CATALOGO.items():
            for campo in entrada["permitidos"]:
                segmentos = set(re.split(r"[^a-z0-9]+", str(campo).lower()))
                with self.subTest(tipo=tipo, campo=campo):
                    self.assertEqual(segmentos & set(PROIBIDOS), set())


class TestTiposGerados(unittest.TestCase):
    def test_ha_um_typed_dict_por_contrato(self) -> None:
        from kamba_core.eventos import contratos

        classes = [n for n in dir(contratos) if n.startswith("Payload")]
        self.assertEqual(len(classes), ESPERADOS)

    def test_um_deles_tem_os_campos_do_contrato(self) -> None:
        """Uma amostra, e nao todos: o que prende todos e o catalogo acima."""
        from kamba_core.eventos.contratos import PayloadOrderPaid

        self.assertEqual(
            sorted(PayloadOrderPaid.__annotations__),
            sorted(CATALOGO["order.paid"]["permitidos"]),
        )


if __name__ == "__main__":
    unittest.main()
