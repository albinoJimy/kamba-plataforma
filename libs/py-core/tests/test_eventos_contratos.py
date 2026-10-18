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
import re
import unittest
from pathlib import Path

from kamba_core.eventos.contratos import CATALOGO

RAIZ = Path(__file__).resolve().parents[3]
CONTRATOS = RAIZ / "contratos" / "eventos"

#: Os trinta e oito do dicionario §3.5, emenda 1.11.
ESPERADOS = 38

#: Os sete do `docs/tecnica/06` §7.3.
PROIBIDOS = ("telefone", "msisdn", "bsuid", "nome", "morada", "texto", "email")


#: Os contratos: 76 ficheiros em 38 pastas, desde o KAM-159.
ESPERADOS_CONTRATOS = 76


def versoes_de(tipo: str) -> list[int]:
    """As versoes de um tipo, lidas da pasta.

    Desde o KAM-159 ha mais do que uma, e **tudo o que este ficheiro verifica
    tem de valer para todas**: um contrato que entrasse como `v2` sem passar
    por aqui herdava verde de uma `v1` que ja nenhum produtor novo escreve.
    """
    numeros = sorted(
        int(p.name[1:-len(".schema.json")])
        for p in (CONTRATOS / tipo).iterdir()
        if re.fullmatch(r"v[1-9][0-9]*\.schema\.json", p.name)
    )
    assert numeros, f"{tipo}: pasta sem nenhum v<N>.schema.json"
    return numeros


def nome_do_exemplo(versao: int) -> str:
    """A `v1` mantem o nome historico; da segunda em diante leva a versao."""
    return "exemplo.json" if versao == 1 else f"exemplo.v{versao}.json"


def payload_de(tipo: str, versao: int = 1) -> dict:
    caminho = CONTRATOS / tipo / f"v{versao}.schema.json"
    return json.loads(caminho.read_text(encoding="utf-8"))["properties"]["payload"]


class TestCatalogoGerado(unittest.TestCase):
    def test_tem_um_tipo_por_contrato(self) -> None:
        na_pasta = sorted(p.name for p in CONTRATOS.iterdir() if p.is_dir())
        self.assertEqual(len(na_pasta), ESPERADOS)
        self.assertEqual(sorted(CATALOGO), na_pasta)

    def test_cada_entrada_diz_as_versoes_dos_ficheiros(self) -> None:
        for tipo, entrada in CATALOGO.items():
            with self.subTest(tipo=tipo):
                self.assertEqual(list(entrada["versoes"]), versoes_de(tipo))

    def test_os_obrigatorios_e_os_permitidos_sao_os_do_schema(self) -> None:
        """Em **todas** as versoes.

        Uma entrada so do catalogo para varias versoes e uma afirmacao: a de
        que o payload tem os mesmos campos em todas. O gerador recusa gerar
        quando nao tem (`NaoSeiTraduzirError`); aqui verifica-se o resultado,
        que e onde a afirmacao se pagaria se fosse falsa.
        """
        medidos = 0
        for tipo, entrada in CATALOGO.items():
            for versao in versoes_de(tipo):
                with self.subTest(tipo=tipo, versao=versao):
                    payload = payload_de(tipo, versao)
                    self.assertEqual(
                        sorted(entrada["obrigatorios"]), sorted(payload.get("required") or [])
                    )
                    self.assertEqual(
                        sorted(entrada["permitidos"]), sorted(payload.get("properties") or {})
                    )
                medidos += 1
        self.assertEqual(medidos, ESPERADOS_CONTRATOS)

    def test_cada_versao_tem_o_seu_exemplo_e_nenhum_sobra(self) -> None:
        """Um `exemplo.v3.json` numa pasta sem `v3.schema.json` passaria
        despercebido para sempre: nada o le. E um `v3.schema.json` sem exemplo
        tirava a versao nova das verificacoes sem falhar nenhuma."""
        for tipo in CATALOGO:
            with self.subTest(tipo=tipo):
                na_pasta = sorted(
                    p.name for p in (CONTRATOS / tipo).iterdir()
                    if p.name.startswith("exemplo")
                )
                self.assertEqual(na_pasta, sorted(map(nome_do_exemplo, versoes_de(tipo))))

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

        # `is_typeddict` e nao `startswith("Payload")`: o
        # `PayloadInvalidoError`, que o validador levanta, tambem comeca por
        # Payload e fazia a contagem dar 39.
        from typing import is_typeddict

        classes = [n for n in dir(contratos) if is_typeddict(getattr(contratos, n))]
        # Um por **contrato**, e nao por tipo: desde o KAM-159 sao 76 em 38
        # pastas. O payload de uma versao nova pode mudar — nos dois
        # `consent.*` muda — e um TypedDict partilhado escondia-o.
        self.assertEqual(len(classes), ESPERADOS_CONTRATOS)
        self.assertTrue(all(n.startswith("Payload") for n in classes))

    def test_um_deles_tem_os_campos_do_contrato(self) -> None:
        """Uma amostra, e nao todos: o que prende todos e o catalogo acima."""
        from kamba_core.eventos.contratos import PayloadOrderPaid

        self.assertEqual(
            sorted(PayloadOrderPaid.__annotations__),
            sorted(CATALOGO["order.paid"]["permitidos"]),
        )

    def test_o_obrigatorio_e_obrigatorio_tambem_em_python(self) -> None:
        """O achado M5: os trinta e oito eram `total=False`.

        Nenhum campo era obrigatorio para um verificador de tipos, e o
        argumento que sustenta o criterio 6 — «essa metade e do compilador,
        pelo tipo gerado» — nao tinha contraparte deste lado: um
        `PayloadOrderCreated()` vazio passava o mypy. O AGR, que produz
        `review.created` e os tres `query.*`, e Python.
        """
        from kamba_core.eventos import contratos

        with_optional = 0
        for tipo, entrada in CATALOGO.items():
            base = "Payload" + "".join(
                p.capitalize() for p in tipo.replace(".", "_").split("_")
            )
            obrigatorios = set(entrada["obrigatorios"])
            opcionais = set(entrada["permitidos"]) - obrigatorios
            with_optional += bool(opcionais)
            for versao in versoes_de(tipo):
                # A `v1` fica com o nome sem sufixo: renomea-la seria quebrar
                # quem a importa por causa de uma versao nova de outro tipo.
                classe = getattr(contratos, base if versao == 1 else f"{base}V{versao}")
                with self.subTest(tipo=tipo, versao=versao):
                    self.assertEqual(set(classe.__required_keys__), obrigatorios)
                    self.assertEqual(set(classe.__optional_keys__), opcionais)
        self.assertGreater(with_optional, 0, "nenhum contrato tem campo opcional: o teste nao prova nada")


class TestValidarPayload(unittest.TestCase):
    """O espelho Python do `validarPayload` de `@kamba/core-ts` (achado M5).

    Nao existia: o `CATALOGO` era gerado e **nada o lia**. Um produtor Python
    — e o AGR e um — nao tinha por onde recusar um tipo desconhecido antes de
    chamar o `evt_emitir`.
    """

    def test_um_payload_completo_passa(self) -> None:
        from kamba_core.eventos.contratos import validar_payload

        validar_payload("order.paid", 1, {
            "order_id": "9b2f6c1a-7e3d-4c80-b5a1-2d9e8f7a6b50",
            "valor_minor": 450000, "currency": "AOA", "paga_via": "referencia",
        })

    def test_um_tipo_sem_contrato_e_recusado_com_a_lista(self) -> None:
        from kamba_core.eventos.contratos import TipoDesconhecidoError, validar_payload

        with self.assertRaises(TipoDesconhecidoError) as apanhado:
            validar_payload("pagamento.feito", 1, {})
        self.assertIn("order.paid", str(apanhado.exception))

    def test_qualquer_versao_publicada_passa(self) -> None:
        """Desde o KAM-159 ha duas, e a `v1` nao deixou de valer por isso.

        E o §6.6 por extenso: «quem quer quebrar escreve `v<N+1>` e deixa o
        `v<N>` como estava». Um validador que so aceitasse a mais recente
        obrigava todos os produtores a migrar no mesmo dia.
        """
        from kamba_core.eventos.contratos import validar_payload

        completo = {
            "order_id": "9b2f6c1a-7e3d-4c80-b5a1-2d9e8f7a6b50",
            "valor_minor": 450000, "currency": "AOA", "paga_via": "referencia",
        }
        for versao in versoes_de("order.paid"):
            with self.subTest(versao=versao):
                validar_payload("order.paid", versao, completo)

    def test_uma_versao_que_nao_existe_e_recusada(self) -> None:
        from kamba_core.eventos.contratos import VersaoDesconhecidaError, validar_payload

        # Uma a mais do que a ultima publicada, calculada e nao escrita: com o
        # `2` literal este teste passou a medir outra coisa no dia em que a
        # `v2` nasceu, e so nao deu verde falso por acaso.
        inexistente = max(versoes_de("order.paid")) + 1
        with self.assertRaises(VersaoDesconhecidaError) as apanhado:
            validar_payload("order.paid", inexistente, {})
        self.assertIn("v1", str(apanhado.exception))

    def test_falta_de_obrigatorio_e_campo_a_mais_saem_na_mesma_mensagem(self) -> None:
        from kamba_core.eventos.contratos import PayloadInvalidoError, validar_payload

        with self.assertRaises(PayloadInvalidoError) as apanhado:
            validar_payload("order.paid", 1, {"order_id": "x", "inventado": 1})
        mensagem = str(apanhado.exception)
        self.assertIn("faltam", mensagem)
        self.assertIn("sobram", mensagem)

    def test_um_evento_sem_payload_aceita_o_dicionario_vazio(self) -> None:
        """`tenant.activated` nao tem campos: o envelope diz tudo."""
        from kamba_core.eventos.contratos import validar_payload

        validar_payload("tenant.activated", 1, {})

    def test_o_limite_esta_declarado_e_medido(self) -> None:
        """Nao verifica tipos nem formatos, e o teste di-lo por extenso.

        O mesmo limite do lado TypeScript: um `valor_minor` em texto passa
        aqui e e o verificador estatico que o apanha. Escrito como teste para
        que a promessa nao cresca sem ninguem decidir.
        """
        from kamba_core.eventos.contratos import validar_payload

        validar_payload("order.paid", 1, {
            "order_id": 42, "valor_minor": "quatrocentos", "currency": "USD",
            "paga_via": None,
        })

    def test_os_tipos_com_contrato_sao_os_do_catalogo(self) -> None:
        from kamba_core.eventos.contratos import tipos_com_contrato

        self.assertEqual(tipos_com_contrato(), sorted(CATALOGO))
        self.assertEqual(len(tipos_com_contrato()), ESPERADOS)


if __name__ == "__main__":
    unittest.main()
