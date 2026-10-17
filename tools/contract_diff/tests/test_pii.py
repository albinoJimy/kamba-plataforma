"""O *lint* de PII: nomes de campo e fixtures (KAM-007, criterio 4).

Os «Testes Requeridos» do bloco pedem «6 nomes proibidos e 2 aprovados». Sao
mais: os **sete** do §7.3 — o bloco diz seis e o §7.3 lista sete (`telefone`,
`msisdn`, `bsuid`, `nome`, `morada`, `texto`, `email`) —, e seis nomes que tem
de passar, escolhidos por serem os que uma implementacao ingenua apanhava por
engano.

A divergencia de contagem fica dita aqui e na seccao de verificacao do bloco:
cumpre-se o §7.3, que e a fonte, e nao o numero do bloco, que a resume mal.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from contract_diff import pii


class TestNomesProibidos(unittest.TestCase):
    """Os sete do §7.3, um teste por nome."""

    def test_os_sete_nomes_do_paragrafo_7_3(self) -> None:
        self.assertEqual(
            pii.PROIBIDOS,
            ("telefone", "msisdn", "bsuid", "nome", "morada", "texto", "email"),
        )

    def test_cada_um_e_apanhado_sozinho(self) -> None:
        for mau in pii.PROIBIDOS:
            with self.subTest(nome=mau):
                self.assertEqual(pii.proibido_em(mau), mau)

    def test_cada_um_e_apanhado_dentro_de_um_nome_composto(self) -> None:
        for mau in pii.PROIBIDOS:
            with self.subTest(nome=mau):
                self.assertEqual(pii.proibido_em(f"do_{mau}_do_cliente"), mau)

    def test_a_caixa_nao_salva_ninguem(self) -> None:
        self.assertEqual(pii.proibido_em("Telefone"), "telefone")
        self.assertEqual(pii.proibido_em("TEXTO_DA_REVIEW"), "texto")


class TestNomesQuePassam(unittest.TestCase):
    """Os que uma implementacao por subcadeia apanhava por engano."""

    PASSAM = (
        # «numero_publico» contem «numero», e nao «nome». Uma procura por
        # subcadeia sobre «nome» tambem nao o apanha — mas apanha os de baixo.
        "numero_publico",
        # «contact_id» e o pseudonimo que o §7.1 **manda** usar.
        "contact_id",
        # «nota» e a classificacao de 1 a 5 de uma review; contem «not», nao
        # «nome». Esta aqui porque e o campo que substitui o texto da review.
        "nota",
        # «motivo» contem «mot»; uma procura desatenta por «morada» com
        # distancia de edicao apanhava-o.
        "motivo",
        # «entrega_modo» e «paga_via» nao tem nada de pessoal, e sao os dois
        # nomes mais compridos do catalogo.
        "entrega_modo",
        "paga_via",
    )

    def test_nenhum_e_apanhado(self) -> None:
        for bom in self.PASSAM:
            with self.subTest(nome=bom):
                self.assertIsNone(pii.proibido_em(bom))

    def test_a_comparacao_e_por_segmento_e_nao_por_subcadeia(self) -> None:
        """A diferenca que torna «numero_publico» aceitavel.

        Com uma procura por subcadeia, qualquer nome que contenha as letras de
        um proibido seria achado — e o lint gritava sobre o que nao e PII, que
        e a forma mais rapida de alguem o desligar.
        """
        self.assertEqual(pii.segmentos("entrega_confirmada_por"),
                         ["entrega", "confirmada", "por"])
        self.assertIsNone(pii.proibido_em("renome"))
        self.assertEqual(pii.proibido_em("renome_do_nome"), "nome")


class TestPadroesDeTelefone(unittest.TestCase):
    """Os do `evt_emitir` e do `pii.ts`, nao o do §7.3. Ver a docstring do modulo."""

    def test_o_movel_angolano_com_e_sem_mais_e_com_e_sem_espaco(self) -> None:
        for texto in ('"+244912345678"', '"244912345678"', '"+244 912345678"'):
            with self.subTest(texto=texto):
                self.assertIsNotNone(pii.TELEFONE_AO.search(texto))

    def test_o_e164_entre_aspas(self) -> None:
        self.assertIsNotNone(pii.E164_ENTRE_ASPAS.search('{"a": "+351912345678"}'))

    def test_um_sku_nao_e_telefone(self) -> None:
        self.assertIsNone(pii.TELEFONE_AO.search('{"sku": "SKU-0001"}'))
        self.assertIsNone(pii.E164_ENTRE_ASPAS.search('{"sku": "SKU-0001"}'))

    def test_sao_os_dois_do_evt_emitir_e_por_essa_ordem(self) -> None:
        """Paridade: um exemplo que este lint aprove e a base recuse era um
        contrato que nao se pode emitir."""
        self.assertEqual(
            [p.pattern for p in pii.PADROES_DE_TELEFONE],
            [r"\+?244 ?9[0-9]{8}", r'"\+[0-9]{9,15}"'],
        )


class TestSobreFicheiros(unittest.TestCase):
    """O lint sobre uma arvore de contratos construida para o efeito."""

    def arvore(self, propriedades: dict, exemplo: dict | None = None) -> Path:
        pasta = Path(tempfile.mkdtemp(prefix="kamba-contratos-"))
        self.addCleanup(lambda: __import__("shutil").rmtree(pasta, ignore_errors=True))
        tipo = pasta / "contratos" / "eventos" / "order.created"
        tipo.mkdir(parents=True)
        (tipo / "v1.schema.json").write_text(
            json.dumps({
                "type": "object", "additionalProperties": False,
                "properties": {
                    "tipo": {"const": "order.created"},
                    "versao": {"const": 1},
                    "payload": {"type": "object", "additionalProperties": False,
                                "properties": propriedades, "required": []},
                },
            }), encoding="utf-8")
        if exemplo is not None:
            (tipo / "exemplo.json").write_text(json.dumps(exemplo), encoding="utf-8")
        return pasta

    def test_um_nome_proibido_num_contrato_e_achado(self) -> None:
        raiz = self.arvore({"telefone": {"type": "string"}})
        (achado,) = pii.nomes(raiz)
        self.assertIn("telefone", achado.porque)
        self.assertEqual(achado.onde, "payload.telefone")

    def test_um_nome_aprovado_deixa_de_ser_achado(self) -> None:
        raiz = self.arvore({"nome_do_servico": {"type": "string"}})
        self.assertEqual(len(pii.nomes(raiz)), 1)
        (raiz / "ci").mkdir()
        (raiz / pii.ALLOWLIST).write_text(
            "version: 1\n"
            "aprovados:\n"
            "  - campo: payload.nome_do_servico\n"
            "    ticket: KAM-007\n"
            "    razao: teste\n"
            "    data: 2026-10-17\n",
            encoding="utf-8",
        )
        self.assertEqual(pii.nomes(raiz), [])

    def test_um_nome_que_so_aparece_no_required_tambem_e_apanhado(self) -> None:
        """Um schema mal formado nao pode ser uma forma de esconder PII."""
        raiz = self.arvore({})
        caminho = raiz / "contratos" / "eventos" / "order.created" / "v1.schema.json"
        documento = json.loads(caminho.read_text(encoding="utf-8"))
        documento["properties"]["payload"]["required"] = ["morada"]
        caminho.write_text(json.dumps(documento), encoding="utf-8")
        (achado,) = pii.nomes(raiz)
        self.assertIn("morada", achado.porque)

    def test_um_telefone_num_exemplo_e_achado(self) -> None:
        raiz = self.arvore({"referencia": {"type": "string"}},
                           exemplo={"referencia": "+244912345678"})
        achados = pii.fixtures(raiz)
        self.assertEqual(len(achados), 1)
        self.assertIn("telefone", achados[0].porque)

    def test_sem_allowlist_o_lint_corre_na_mesma(self) -> None:
        """A lista e uma excepcao, nao uma dependencia."""
        raiz = self.arvore({"order_id": {"type": "string"}})
        self.assertEqual(pii.ler_allowlist(raiz), set())
        self.assertEqual(pii.nomes(raiz), [])


if __name__ == "__main__":
    unittest.main()
