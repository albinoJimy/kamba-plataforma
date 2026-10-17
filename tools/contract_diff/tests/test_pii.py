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


class TestOBuracoDoSegmentoExacto(unittest.TestCase):
    """O achado C1: a primeira versao do lint quase nao apanhava nada.

    A comparacao era por segmento **exacto** contra os sete nomes do §7.3, e
    bastava um «s» para passar: `nomes`, `telefones`, `emails` e `moradas`
    atravessavam o lint inteiro. O ingles atravessava-o todo — `phone`,
    `mail`, `address`, `full_name` — e as abreviaturas tambem. A revisao
    adversarial demonstrou-o com vinte e tal nomes; ficam aqui, porque a
    unica forma de uma correccao destas nao se desfazer e a lista dos casos
    que a motivaram estar escrita.
    """

    #: Exactamente os nomes que a revisao demonstrou a passar.
    PASSAVAM = (
        "nomes", "telefones", "emails", "moradas", "textos", "msisdns", "bsuids",
        "phone", "telephone", "mail", "e_mail", "address", "endereco",
        "mensagem", "msg", "conteudo", "observacoes", "wa_id",
        "destinatario", "remetente", "titular",
        "full_name", "fullname", "first_name", "customer_name",
    )

    def test_nenhum_deles_passa_hoje(self) -> None:
        for nome in self.PASSAVAM:
            with self.subTest(nome=nome):
                self.assertIsNotNone(pii.proibido_em(nome), f"{nome} continua a passar")

    def test_o_plural_de_cada_um_dos_sete_e_apanhado(self) -> None:
        for mau in pii.PROIBIDOS:
            with self.subTest(nome=mau):
                self.assertIsNotNone(pii.proibido_em(mau + "s"))
                self.assertIsNotNone(pii.proibido_em("do_" + mau + "s"))

    def test_as_duas_convencoes_de_escrita_dao_o_mesmo(self) -> None:
        """`full_name` e `fullName` sao o mesmo campo em sitios diferentes."""
        for nome in ("full_name", "fullName", "FullName", "full-name"):
            with self.subTest(nome=nome):
                self.assertIsNotNone(pii.proibido_em(nome))

    def test_e_os_que_tem_de_passar_continuam_a_passar(self) -> None:
        """A correccao nao vale nada se fizer o lint gritar sobre tudo.

        Estes sao campos reais dos trinta e oito contratos: um falso positivo
        aqui e uma excepcao a declarar em `ci/contratos-allow.yaml`, e uma
        lista de excepcoes longa e uma lista que ninguem le.
        """
        reais = (
            "numero_publico", "contact_id", "nota", "motivo", "entrega_modo",
            "paga_via", "order_id", "sku", "qty", "linhas", "currency",
            "expira_at", "autenticacao", "authn_ok", "provider_event_id",
            "plano", "review_id", "merged_into", "channel_mode", "thread_id",
            "turn_id", "booking_id", "service_id", "resource_id", "inicio_at",
            "finalidade", "origem", "estado", "preco_tipo", "preco_minor",
            "total_minor", "valor_minor", "referencia", "provider", "vertical",
        )
        for nome in reais:
            with self.subTest(nome=nome):
                self.assertIsNone(pii.proibido_em(nome), f"{nome} passou a ser falso positivo")

    def test_uma_palavra_que_so_comeca_pela_raiz_nao_conta(self) -> None:
        """Nao se usa `startswith`: `nomeacao` nao e um nome de pessoa."""
        for nome in ("nomeacao", "nomeado_por", "textura", "emailing_id"):
            with self.subTest(nome=nome):
                self.assertIsNone(pii.proibido_em(nome))


class TestOPercursoEhTotal(unittest.TestCase):
    """O achado m4: o lint calava-se perante metade do JSON Schema.

    Visitava `properties`, `required`, `dependentRequired`, `propertyNames` e
    `items`, e mais nada: `$defs`, `oneOf`, `allOf`, `anyOf`,
    `patternProperties` e `additionalProperties`-como-schema passavam sem
    aviso. Nenhum contrato os usa hoje — e era precisamente por isso que
    ninguem ia reparar no dia em que um usasse. O contraste era com o
    `diff.py`, que trata o desconhecido como quebrante, e com o proprio gate
    3b, que **segue** `$ref` internos.
    """

    def nomes(self, documento: dict) -> set:
        return {nome for _caminho, nome in pii._nomes_de_campo(documento)}

    def test_dentro_de_defs(self) -> None:
        self.assertIn("telefone", self.nomes(
            {"$defs": {"corpo": {"properties": {"telefone": {"type": "string"}}}}}
        ))

    def test_dentro_de_one_of_all_of_any_of(self) -> None:
        for palavra in ("oneOf", "allOf", "anyOf"):
            with self.subTest(palavra=palavra):
                self.assertIn("morada", self.nomes(
                    {palavra: [{"properties": {"morada": {"type": "string"}}}]}
                ))

    def test_dentro_de_pattern_properties_e_de_additional_properties(self) -> None:
        self.assertIn("email", self.nomes(
            {"patternProperties": {"^x_": {"properties": {"email": {}}}}}
        ))
        self.assertIn("email", self.nomes(
            {"additionalProperties": {"properties": {"email": {}}}}
        ))

    def test_dentro_de_prefix_items(self) -> None:
        self.assertIn("nome", self.nomes({"prefixItems": [{"properties": {"nome": {}}}]}))

    def test_uma_palavra_chave_que_ainda_nao_existe(self) -> None:
        """A razao de o percurso ser total e nao uma lista: o JSON Schema cresce."""
        self.assertIn("bsuid", self.nomes(
            {"palavraQueAindaNaoFoiInventada": {"properties": {"bsuid": {}}}}
        ))

if __name__ == "__main__":
    unittest.main()
