"""KAM-122: o compositor das artes do social (criterios 1 e 2).

**As cadeias esperadas estao escritas a mao**, e nao calculadas pelo
`formatar_kz` nem pelo `quebrar`: um oraculo importado do alvo passava com o
alvo errado. Os telefones sao do intervalo ficticio `999`.
"""

from __future__ import annotations

import datetime
import unittest

from kamba_agr.social import arte, publicacao
from kamba_agr.social.regras import Facto, Perfil

DIA = datetime.date(2026, 11, 25)
ATE_NATAL = datetime.date(2026, 12, 31)


def promocao(texto: str, ate: datetime.date = ATE_NATAL) -> Facto:
    return Facto(texto, promocao=True, valido_ate=ate)


def perfil(nome: str, factos: tuple[Facto | str, ...], categoria: str = "moda") -> Perfil:
    return Perfil(
        tenant_id="11111111-1111-4111-8111-111111111111",
        nome=nome,
        categoria=categoria,
        tom="proximo",
        cores=("#AA0000",),
        publico="familias",
        slots=(),
        factos=tuple(f if isinstance(f, Facto) else Facto(f) for f in factos),
    )


#: Os cinquenta casos do criterio 1: (nome, factos, tipo do item, cadeia esperada).
#: *Template* `produtos_faixa` (nome em 22 caracteres, destaque em 30), quadrado.
CASOS: tuple[tuple[str, tuple[Facto | str, ...], str, str], ...] = (
    # ---- produto: o facto com preco, sem o valor, e o preco na linha propria
    ("Doçaria São João", ("Bolo de chocolate a 12.500 Kz",), "produto", "Doçaria São João\nBolo de chocolate\n12.500 Kz"),
    ("Pão Quente da Avó", ("Pão caseiro a 850 Kz",), "produto", "Pão Quente da Avó\nPão caseiro\n850 Kz"),
    ("Moda Kianda", ("Vestido de capulana a 25000 Kz",), "produto", "Moda Kianda\nVestido de capulana\n25.000 Kz"),
    ("Ótica Luanda", ("Óculos de sol: 18 500 kwanzas",), "produto", "Ótica Luanda\nÓculos de sol\n18.500 Kz"),
    ("Café Muxima", ("Café torrado 1.250 Kz",), "produto", "Café Muxima\nCafé torrado\n1.250 Kz"),
    ("Açaí & Companhia", ("Taça de açaí por 3.000 AOA",), "produto", "Açaí & Companhia\nTaça de açaí\n3.000 Kz"),
    (
        "Sapataria Kilamba",
        ("Sapatilhas a 45 000 Kz", "Encomendas: 999 100 200"),
        "produto",
        "Sapataria Kilamba\nSapatilhas\n45.000 Kz\n999 100 200",
    ),
    ("Electrónica Mutamba", ("Rádio portátil a 1.250.000 Kz",), "produto", "Electrónica Mutamba\nRádio portátil\n1.250.000 Kz"),
    (
        "Costura Fina da Conceição",
        ("Fato à medida a 75.000 Kz",),
        "produto",
        "Costura Fina da\nConceição\nFato à medida\n75.000 Kz",
    ),
    ("Salão Beleza Negra", ("Tranças a 12.500,50 Kz",), "produto", "Salão Beleza Negra\nTranças\n12.500,50 Kz"),
    (
        "Mãe Kambuta Petiscos",
        ("Prato do dia a 2 500 Kz", "Ligue 999 300 400"),
        "produto",
        "Mãe Kambuta Petiscos\nPrato do dia\n2.500 Kz\n999 300 400",
    ),
    ("Livraria Mãe Ganga", ("Caderno escolar a 600 kwanzas",), "produto", "Livraria Mãe Ganga\nCaderno escolar\n600 Kz"),
    ("Panificadora Ngola", ("Broa por 150 Kz",), "produto", "Panificadora Ngola\nBroa\n150 Kz"),
    ("Têxteis Kwanza Sul", ("Lençóis de algodão a 9.990 Kz",), "produto", "Têxteis Kwanza Sul\nLençóis de algodão\n9.990 Kz"),
    (
        "Frutaria Ilha",
        ("Cesta de fruta a 7500 Kz", "WhatsApp 999 555 111", "Também 999 555 222"),
        "produto",
        "Frutaria Ilha\nCesta de fruta\n7.500 Kz\n999 555 111\n999 555 222",
    ),
    ("Peças Viana", ("Filtro de óleo a 4.200 Kz", "Entregas em Viana"), "produto", "Peças Viana\nFiltro de óleo\n4.200 Kz"),
    ("Boutique Maianga", ("Saia plissada a 15.000 Kz",), "produto", "Boutique Maianga\nSaia plissada\n15.000 Kz"),
    ("Gelataria Kinaxixi", ("Gelado de múcua a 1.000 Kz",), "produto", "Gelataria Kinaxixi\nGelado de múcua\n1.000 Kz"),
    ("Joias da Rainha Njinga", ("Anel de prata a 35.000 Kz",), "produto", "Joias da Rainha Njinga\nAnel de prata\n35.000 Kz"),
    ("Cosméticos Lueji", ("Creme hidratante a 6.750 Kz",), "produto", "Cosméticos Lueji\nCreme hidratante\n6.750 Kz"),
    (
        "Restaurante Ponto Final",
        ("Mufete completo a 8.500 Kz",),
        "produto",
        "Restaurante Ponto\nFinal\nMufete completo\n8.500 Kz",
    ),
    (
        "Calçado Cazenga",
        ("Chinelos por 2.000 Kz", "Reservas: 999 777 888"),
        "produto",
        "Calçado Cazenga\nChinelos\n2.000 Kz\n999 777 888",
    ),
    ("Mercearia São Paulo", ("Arroz 25 kg a 22.000 Kz",), "produto", "Mercearia São Paulo\nArroz 25 kg\n22.000 Kz"),
    ("Bazar Cuca", ("Panela de pressão a 18.000 Kz",), "produto", "Bazar Cuca\nPanela de pressão\n18.000 Kz"),
    (
        "Doces da Tia Fátima",
        ("Pudim a 3.500 Kz", "999 222 333"),
        "produto",
        "Doces da Tia Fátima\nPudim\n3.500 Kz\n999 222 333",
    ),
    # ---- promocao: o facto inteiro, com os valores normalizados e indivisiveis
    (
        "Moda Kianda",
        (promocao("20% de desconto em vestidos até 31/12"),),
        "promocao",
        "Moda Kianda\n20% de desconto em vestidos\naté 31/12",
    ),
    (
        "Doçaria São João",
        (promocao("Bolo de aniversário a 10000 Kz até 24/12"),),
        "promocao",
        "Doçaria São João\nBolo de aniversário a\n10.000 Kz até 24/12",
    ),
    (
        "Salão Beleza Negra",
        (promocao("Leve dois pague um nas tranças até 15/12"),),
        "promocao",
        "Salão Beleza Negra\nLeve dois pague um nas tranças\naté 15/12",
    ),
    (
        "Frutaria Ilha",
        (promocao("Manga a 500 Kz até 20/12"), "999 555 111"),
        "promocao",
        "Frutaria Ilha\nManga a 500 Kz até 20/12\n999 555 111",
    ),
    ("Café Muxima", (promocao("Segundo café grátis até 10/12"),), "promocao", "Café Muxima\nSegundo café grátis até 10/12"),
    ("Ótica Luanda", (promocao("15% em armações até 31/12"),), "promocao", "Ótica Luanda\n15% em armações até 31/12"),
    (
        "Bazar Cuca",
        (promocao("Desconto de 5000 kwanzas em panelas até 30/11"),),
        "promocao",
        "Bazar Cuca\nDesconto de 5.000 Kz em\npanelas até 30/11",
    ),
    (
        "Boutique Maianga",
        (promocao("Saias a 9 990 Kz até 31/12"), "Saia plissada a 15.000 Kz"),
        "promocao",
        "Boutique Maianga\nSaias a 9.990 Kz até 31/12",
    ),
    (
        "Pão Quente da Avó",
        (promocao("Pão a 700 Kz só esta semana até 28/11"),),
        "promocao",
        "Pão Quente da Avó\nPão a 700 Kz só esta semana\naté 28/11",
    ),
    (
        "Cosméticos Lueji",
        (promocao("Oferta de amostra até 20/12"), "Pedidos: 999123456"),
        "promocao",
        "Cosméticos Lueji\nOferta de amostra até 20/12\n999 123 456",
    ),
    # ---- dica e bastidores: so o nome e os contactos
    ("Moda Kianda", ("Vestido de capulana a 25000 Kz",), "dica", "Moda Kianda"),
    ("Sapataria Kilamba", ("Encomendas: 999 100 200",), "bastidores", "Sapataria Kilamba\n999 100 200"),
    ("Doçaria São João", ("Ligue +244 999 432 100",), "dica", "Doçaria São João\n999 432 100"),
    ("Açaí & Companhia", ("Pedidos 999876543",), "bastidores", "Açaí & Companhia\n999 876 543"),
    (
        "Costura Fina da Conceição",
        ("Atendemos de segunda a sábado",),
        "dica",
        "Costura Fina da\nConceição",
    ),
    ("Electrónica Mutamba", (), "bastidores", "Electrónica Mutamba"),
    (
        "Restaurante Ponto Final",
        ("Reservas 999 010 020", "Delivery 999 030 040", "Eventos 999 050 060"),
        "dica",
        "Restaurante Ponto\nFinal\n999 010 020\n999 030 040",
    ),
    ("Peças Viana", ("Oficina na Estrada de Catete",), "bastidores", "Peças Viana"),
    # ---- produto sem facto com preco: so o nome e os contactos
    ("Gelataria Kinaxixi", ("Sabores de fruta da terra",), "produto", "Gelataria Kinaxixi"),
    ("Bazar Cuca", ("Ligue 999 600 700",), "produto", "Bazar Cuca\n999 600 700"),
    # ---- o preco da promocao nao serve de preco a um item produto
    (
        "Moda Kianda",
        (promocao("Vestidos a 9.000 Kz até 31/12"), "Blusas a 4.500 Kz"),
        "produto",
        "Moda Kianda\nBlusas\n4.500 Kz",
    ),
    # ---- o primeiro facto com preco e o do item
    (
        "Livraria Mãe Ganga",
        ("Livros novos toda a semana", "Lápis a 100 Kz", "Mochila a 7.000 Kz"),
        "produto",
        "Livraria Mãe Ganga\nLápis\n100 Kz",
    ),
    # ---- uma promocao fora de prazo nao entra; a outra sim
    (
        "Café Muxima",
        (promocao("Café duplo a 400 Kz até 20/11", datetime.date(2026, 11, 20)), promocao("Bolo grátis até 30/11")),
        "promocao",
        "Café Muxima\nBolo grátis até 30/11",
    ),
    # ---- o mesmo telefone duas vezes conta uma
    (
        "Frutaria Ilha",
        ("WhatsApp 999 555 111", "Chamadas 999555111"),
        "dica",
        "Frutaria Ilha\n999 555 111",
    ),
    ("Têxteis Kwanza Sul", ("Toalhas a 1.500,00 Kz",), "produto", "Têxteis Kwanza Sul\nToalhas\n1.500 Kz"),
)


class TestFormatos(unittest.TestCase):
    def test_o_preco_no_formato_do_bloco(self) -> None:
        self.assertEqual(arte.formatar_kz(1_250_000), "12.500 Kz")
        self.assertEqual(arte.formatar_kz(1_250_050), "12.500,50 Kz")
        self.assertEqual(arte.formatar_kz(85_000), "850 Kz")
        self.assertEqual(arte.formatar_kz(0), "0 Kz")
        self.assertEqual(arte.formatar_kz(125_000_000), "1.250.000 Kz")
        with self.assertRaises(ValueError):
            arte.formatar_kz(-1)

    def test_tres_templates_por_tipo_nos_dois_formatos(self) -> None:
        for tipo in arte.TIPOS_DE_NEGOCIO:
            self.assertGreaterEqual(len(arte.templates_do_tipo(tipo)), 3)
            self.assertLessEqual(len(arte.templates_do_tipo(tipo)), 5)
        self.assertEqual(arte.FORMATOS, {"quadrado": (1080, 1080), "retrato": (1080, 1350)})

    def test_o_tipo_de_negocio_pela_categoria(self) -> None:
        self.assertEqual(arte.tipo_de_negocio("Bolos e doces"), "alimentacao")
        self.assertEqual(arte.tipo_de_negocio("Salão de cabeleireiro"), "servicos")
        self.assertEqual(arte.tipo_de_negocio("Roupa de senhora"), "produtos")
        self.assertEqual(arte.tipo_de_negocio(None), "produtos")


class TestCinquentaCasos(unittest.TestCase):
    """Criterio 1: o texto composto e **identico** a cadeia esperada nos 50 casos."""

    def test_sao_cinquenta(self) -> None:
        self.assertEqual(len(CASOS), 50)

    def test_os_cinquenta_casos_sao_identicos_a_cadeia_esperada(self) -> None:
        template = arte.TEMPLATES["produtos_faixa"]
        for nome, factos, tipo, esperado in CASOS:
            with self.subTest(nome=nome, tipo=tipo, esperado=esperado):
                p = perfil(nome, factos)
                composicao = arte.compor(arte.dados_da_arte(p, tipo, DIA), template, "quadrado")
                self.assertEqual(arte.texto_composto(composicao), esperado)
                # E cada linha passa a guarda de numeros contra os factos.
                arte.verificar_numeros(composicao, p.factos_validos(DIA), nome)

    def test_nenhuma_linha_parte_um_valor_ou_um_telefone(self) -> None:
        template = arte.TEMPLATES["produtos_cartaz"]  # o mais estreito: 16 e 24
        p = perfil("Bazar Cuca", (promocao("Panelas grandes com desconto de 12.500 Kz até 31/12"), "Ligue 999 600 700"))
        linhas = arte.texto_composto(arte.compor(arte.dados_da_arte(p, "promocao", DIA), template, "retrato")).split("\n")
        # A largura do cartaz (24) cai a meio de «12.500 Kz»: sem a uniao, partia-se.
        self.assertTrue(any("12.500 Kz" in linha for linha in linhas), linhas)
        self.assertIn("999 600 700", linhas)

    def test_um_texto_que_nao_cabe_e_recusado_e_nao_cortado(self) -> None:
        template = arte.TEMPLATES["produtos_cartaz"]
        nome = "Comercial Geral Grande Armazem Central de Luanda Sul"
        with self.assertRaises(arte.Recusa) as recusa:
            arte.compor(arte.DadosDaArte(nome), template, "quadrado")
        self.assertEqual(recusa.exception.motivo, "texto_nao_cabe")

    def test_uma_promocao_sem_facto_valido_nao_compoe(self) -> None:
        p = perfil("Moda Kianda", (promocao("10% até 01/11", datetime.date(2026, 11, 1)),))
        with self.assertRaises(arte.Recusa) as recusa:
            arte.dados_da_arte(p, "promocao", DIA)
        self.assertEqual(recusa.exception.motivo, "faltam_factos")


class TestCemAdversariais(unittest.TestCase):
    """Criterio 2: **0** valores monetarios na arte sem facto, em 100 tentativas adversariais.

    Cada tentativa poe um valor no sitio onde um atacante o poria — o nome da
    marca, a categoria, um facto vencido, um facto de outro dia — ou forja a
    composicao. A arte so leva o que os factos validos tem, e a guarda recusa o
    resto.
    """

    def _composicoes(self) -> list[tuple[arte.Composicao | None, Perfil]]:
        template = arte.TEMPLATES["produtos_faixa"]
        saidas: list[tuple[arte.Composicao | None, Perfil]] = []
        for i in range(25):
            valor = f"{(i + 1) * 1000} Kz"
            casos = (
                # 1. O valor so numa promocao vencida.
                perfil("Moda Kianda", (promocao(f"Vestidos a {valor} até 01/11", datetime.date(2026, 11, 1)),)),
                # 2. O valor na categoria, que nao e facto.
                perfil("Moda Kianda", ("Entregas em Luanda",), categoria=f"roupa a {valor}"),
                # 3. Um facto sem valor num item produto: a arte nao inventa preco.
                perfil("Moda Kianda", ("Vestidos de capulana",)),
                # 4. Um telefone so na categoria.
                perfil("Moda Kianda", (), categoria=f"ligue 999 {100 + i} 000"),
            )
            for p in casos:
                try:
                    tipo = "promocao" if p.factos and p.factos[0].promocao else "produto"
                    saidas.append((arte.compor(arte.dados_da_arte(p, tipo, DIA), template, "quadrado"), p))
                except arte.Recusa:
                    saidas.append((None, p))
        return saidas

    def test_cem_tentativas_zero_valores_sem_facto(self) -> None:
        saidas = self._composicoes()
        self.assertEqual(len(saidas), 100)
        for composicao, p in saidas:
            if composicao is None:
                continue
            texto = arte.texto_composto(composicao)
            self.assertNotIn("Kz", texto, texto)
            self.assertNotRegex(texto, r"\d", texto)

    def test_uma_composicao_forjada_e_recusada_pela_guarda(self) -> None:
        template = arte.TEMPLATES["produtos_faixa"]
        p = perfil("Moda Kianda", ("Blusas a 4.500 Kz", "Ligue 999 600 700"))
        forjados = (
            arte.DadosDaArte("Moda Kianda", "Blusas", 500_000),  # outro preco
            arte.DadosDaArte("Moda Kianda", "Blusas 50% de desconto", 450_000),  # percentagem sem facto
            arte.DadosDaArte("Moda Kianda", "Blusas", 450_000, ("999 600 701",)),  # outro telefone
        )
        recusados = 0
        for dados in forjados:
            composicao = arte.compor(dados, template, "quadrado")
            try:
                arte.verificar_numeros(composicao, p.factos_validos(DIA), p.nome or "")
            except arte.Recusa:
                recusados += 1
        self.assertEqual(recusados, 3)


class TestSocialPublisher(unittest.TestCase):
    """Criterio 7: so a `ManualDelivery` existe, e o `publish()` lanca `NotEnabled`."""

    PEDIDO = publicacao.PedidoDeEntrega(
        content_item_id="7a2e3f4b-5c6d-4e7f-8a9b-0c1d2e3f4a5b",
        tenant_id="11111111-1111-4111-8111-111111111111",
        legenda="Legenda aprovada",
        arte_ref="t/11111111-1111-4111-8111-111111111111/arte/x.jpg",
        is_ai_generated=True,
        primeira_entrega=True,
    )

    def test_publish_lanca_not_enabled(self) -> None:
        with self.assertRaises(publicacao.NotEnabled):
            publicacao.ManualDelivery().publish(self.PEDIDO)

    def test_so_a_manual_delivery_implementa_o_publisher(self) -> None:
        implementacoes = [
            nome
            for nome, valor in vars(publicacao).items()
            if isinstance(valor, type) and callable(getattr(valor, "deliver", None)) and valor is not publicacao.SocialPublisher
        ]
        self.assertEqual(implementacoes, ["ManualDelivery"])

    def test_a_entrega_leva_a_nota_de_ia_e_os_termos_so_na_primeira(self) -> None:
        entrega = publicacao.ManualDelivery().deliver(self.PEDIDO)
        self.assertEqual(entrega.legenda, "Legenda aprovada")
        self.assertEqual(entrega.nota, publicacao.NOTA_DO_ROTULO_DE_IA)
        self.assertEqual(entrega.termos, publicacao.TERMOS_DA_PRIMEIRA_ENTREGA)
        segunda = publicacao.ManualDelivery().deliver(
            publicacao.PedidoDeEntrega(**{**vars(self.PEDIDO), "primeira_entrega": False})
        )
        self.assertIsNone(segunda.termos)

    def test_os_textos_fixos_nao_tem_digitos(self) -> None:
        # Vao ao `send` sem passar pelo validador (aresta 34).
        for texto in (publicacao.NOTA_DO_ROTULO_DE_IA, publicacao.TERMOS_DA_PRIMEIRA_ENTREGA):
            self.assertNotRegex(texto, r"\d")


if __name__ == "__main__":
    unittest.main()
