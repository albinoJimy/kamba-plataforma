"""O validador de citacao (KAM-032): unidade, propriedade, adversarial, canon.

    TestNoveFormatos        os nove formatos do criterio 1, **um teste cada**
    TestMoeda               moeda diferente de Kz, e o limite que isso tem hoje
    TestExtensoPorPropriedade  ida-e-volta sobre 0..200000, por geracao
    TestExtraccao           a ordem das classes, e o que cai em `outro`
    TestSeteVeredictos      um teste por veredicto, com o controlo positivo ao lado
    TestVinculoSkuPreco     «produto errado com preco certo» e o §6.3
    TestModosDePreco        `fixo`, `a_partir_de`, `sob_consulta` (criterio 4)
    TestRenderer            os cinco blocos, e o que o *renderer* recusa
    TestIdaEVolta           **integracao**: `compose -> validate -> render`
    TestMetricas            as cinco, o eixo `vertical`, e o `tenant_id` a levantar
    TestConjuntoAdversarial o gate duro: 0 falsos aceites **e** 0 falsos rejeitos
    TestLimitesAssumidos    as limitacoes do §9.2, medidas em vez de esquecidas
    TestCanon               os nomes aqui sao os do dicionario §3.30
    TestGateDeCobertura     o caminho do modulo bate no estrato `critico`

O conjunto adversarial vive em `casos_adversariais.py` porque o *golden* do
KAM-040 o le de la («Regressao: o conjunto adversarial entra no *golden*»).
"""

from __future__ import annotations

import random
import re
import unittest
from pathlib import Path

from kamba_agr.contexto import VERTICAIS
from kamba_agr.metricas import (
    METRICA_RENDER_ONLY,
    METRICA_VALIDATE,
    METRICA_VALIDATE_FALHAS,
    METRICA_VALIDATE_HANDOFF,
    METRICA_VALIDATE_REPETICOES,
    METRICAS_DO_VALIDADOR,
    EtiquetaInvalida,
    MetricasDoAgr,
)
from kamba_agr.tls.erros import KINDS, Fact
from kamba_agr.validador import extraccao, normalizacao, render, veredicto

import casos_adversariais as ca

_RAIZ = Path(__file__).resolve().parents[3]

#: O valor dos nove formatos do criterio 1, em centimos.
DOZE_MIL_E_QUINHENTOS = 1250000


# ------------------------------------------------- criterio 1: nove formatos
class TestNoveFormatos(unittest.TestCase):
    """Um teste por formato, **a letra do criterio 1**.

    O criterio escreve «(9 formatos, 1 teste cada)». Um `subTest` sobre uma
    tabela cumpria-o em espirito e nao a letra — e a diferenca nao e estetica:
    nove testes nomeados aparecem nove vezes no relatorio, e um que se parta
    diz qual formato se partiu.
    """

    def test_01_inteiro_nu(self) -> None:
        self.assertEqual(normalizacao.para_centimos("12500"), DOZE_MIL_E_QUINHENTOS)

    def test_02_ponto_de_milhares(self) -> None:
        self.assertEqual(normalizacao.para_centimos("12.500"), DOZE_MIL_E_QUINHENTOS)

    def test_03_espaco_de_milhares(self) -> None:
        self.assertEqual(normalizacao.para_centimos("12 500"), DOZE_MIL_E_QUINHENTOS)

    def test_04_virgula_de_milhares(self) -> None:
        """`12,500` le-se 12500 e nao 12,5 — e a regra 2 do `normalizacao.py`."""
        self.assertEqual(normalizacao.para_centimos("12,500"), DOZE_MIL_E_QUINHENTOS)

    def test_05_com_kz_no_fim(self) -> None:
        self.assertEqual(normalizacao.para_centimos("12500 Kz"), DOZE_MIL_E_QUINHENTOS)

    def test_06_ponto_e_virgula_decimal(self) -> None:
        self.assertEqual(
            normalizacao.para_centimos("12.500,00 Kz"), DOZE_MIL_E_QUINHENTOS
        )

    def test_07_com_kz_a_frente(self) -> None:
        self.assertEqual(normalizacao.para_centimos("Kz 12.500"), DOZE_MIL_E_QUINHENTOS)

    def test_08_multiplicador_mil(self) -> None:
        """`12,5 mil`: aqui a virgula e decimal, ao contrario do formato 4."""
        self.assertEqual(normalizacao.para_centimos("12,5 mil"), DOZE_MIL_E_QUINHENTOS)

    def test_09_por_extenso(self) -> None:
        self.assertEqual(
            normalizacao.para_centimos("doze mil e quinhentos"), DOZE_MIL_E_QUINHENTOS
        )

    def test_a_unidade_e_o_centimo_e_nao_o_kz(self) -> None:
        """O criterio escreve `value_kz`; o §2 e o KAM-139 dizem centimos.

        Sem isto a comparacao com o `preco_minor` do `docs/tecnica/05` §6.3
        falhava **sempre**, por um factor de cem (divida 106, emenda 1.39).
        """
        self.assertEqual(normalizacao.para_centimos("1 Kz"), 100)
        self.assertEqual(normalizacao.CENTIMOS_POR_KZ, 100)

    def test_mais_de_duas_casas_decimais_levanta(self) -> None:
        """Arredondar dinheiro em silencio e o que o §2 existe para nao ter."""
        with self.assertRaises(normalizacao.NaoEDinheiroError):
            normalizacao.para_centimos("12.500,123 Kz")

    def test_os_centimos_aparecem_na_apresentacao(self) -> None:
        self.assertEqual(normalizacao.kz_display(2075050), "20 750,50 Kz")
        self.assertEqual(normalizacao.kz_display(1250000), "12 500 Kz")


class TestNormalizacaoRecusa(unittest.TestCase):
    """As recusas do parser, uma por caminho.

    Sao as linhas *fail-closed* do ficheiro, e num parser de dinheiro e onde
    mora o risco: cada uma delas, se passasse em vez de levantar, punha um
    numero adivinhado no lugar de um numero lido.
    """

    def test_texto_vazio(self) -> None:
        with self.assertRaises(normalizacao.NaoEDinheiroError):
            normalizacao.para_centimos("   ")
        with self.assertRaises(normalizacao.NaoEDinheiroError):
            normalizacao.extenso_para_int(" e ")

    def test_digitos_com_letra_colada(self) -> None:
        with self.assertRaises(normalizacao.NaoEDinheiroError):
            normalizacao.para_centimos("1a")

    def test_parte_decimal_ilegivel(self) -> None:
        with self.assertRaises(normalizacao.NaoEDinheiroError):
            normalizacao.para_centimos("12, 50")

    def test_palavra_final_que_nao_e_multiplicador(self) -> None:
        with self.assertRaises(normalizacao.NaoEDinheiroError):
            normalizacao.para_centimos("12 banana")

    def test_mil_sozinho_vale_mil_kz(self) -> None:
        """O grupo vazio antes de uma escala vale um (`extenso_para_int`)."""
        self.assertEqual(normalizacao.para_centimos("mil"), 100000)
        self.assertEqual(normalizacao.para_centimos("Kz mil"), 100000)

    def test_ponto_com_uma_casa_e_decimal_e_nao_milhares(self) -> None:
        """Regra 5: `12.5` nao pode ser milhares — um grupo tem tres digitos."""
        self.assertEqual(normalizacao.para_centimos("12.5 Kz"), 1250)

    def test_dinheiro_negativo_nao_se_apresenta(self) -> None:
        with self.assertRaises(ValueError):
            normalizacao.kz_display(-1)

    def test_zero_apresenta_se(self) -> None:
        self.assertEqual(normalizacao.kz_display(0), "0 Kz")


class TestMoeda(unittest.TestCase):
    def test_kz_aoa_e_kwanzas_passam(self) -> None:
        for marca in ("12500 Kz", "12500 AOA", "12500 kwanzas", "12500 kwanza"):
            with self.subTest(marca=marca):
                self.assertEqual(
                    normalizacao.para_centimos(marca), DOZE_MIL_E_QUINHENTOS
                )

    def test_moeda_estrangeira_levanta(self) -> None:
        for marca in ("100 USD", "$100", "100 EUR", "100 ZAR", "R$ 100"):
            with self.subTest(marca=marca):
                with self.assertRaises(normalizacao.MoedaEstrangeiraError):
                    normalizacao.para_centimos(marca)

    def test_o_lado_positivo_deste_criterio_e_inverificavel_hoje(self) -> None:
        """«moeda diferente de Kz **sem *fact* de moeda** e erro» (criterio 1).

        Nao existe `kind` de moeda e nao pode existir: o `KINDS` do KAM-028 esta
        fechado em quatro. Pelo que *toda* a moeda estrangeira e erro, e a
        metade «com *fact*» do criterio nao se consegue medir. O credor e o
        KAM-031 (divida 105), e este teste existe para que a afirmacao nao se
        leia como mais forte do que e.
        """
        self.assertEqual(KINDS, ("price", "stock", "total", "datetime"))
        self.assertNotIn("currency", KINDS)
        self.assertNotIn("discount", KINDS)


# --------------------------------------------- propriedade sobre o extenso
def _em_extenso(n: int) -> str:
    """Um inteiro escrito por extenso. **Existe so no teste**, de proposito.

    O *renderer* escreve digitos e nunca palavras, pelo que um gerador em
    producao era codigo que ninguem chamava. Aqui serve de segunda
    implementacao: a propriedade e `extenso_para_int(_em_extenso(n)) == n`, e e
    ela que apanha os casos que uma tabela escrita a mao nao tem.
    """
    unidades = [
        "zero", "um", "dois", "tres", "quatro", "cinco", "seis", "sete", "oito",
        "nove", "dez", "onze", "doze", "treze", "catorze", "quinze", "dezasseis",
        "dezassete", "dezoito", "dezanove",
    ]
    dezenas = {
        2: "vinte", 3: "trinta", 4: "quarenta", 5: "cinquenta", 6: "sessenta",
        7: "setenta", 8: "oitenta", 9: "noventa",
    }
    centenas = {
        1: "cento", 2: "duzentos", 3: "trezentos", 4: "quatrocentos",
        5: "quinhentos", 6: "seiscentos", 7: "setecentos", 8: "oitocentos",
        9: "novecentos",
    }

    def abaixo_de_mil(v: int) -> str:
        if v == 0:
            return ""
        if v == 100:
            return "cem"
        partes = []
        if v >= 100:
            partes.append(centenas[v // 100])
            v %= 100
        if v >= 20:
            partes.append(dezenas[v // 10])
            v %= 10
            if v:
                partes.append(unidades[v])
        elif v:
            partes.append(unidades[v])
        return " e ".join(partes)

    if n == 0:
        return "zero"
    partes = []
    milhoes, resto = divmod(n, 10**6)
    if milhoes:
        partes.append(
            "um milhao" if milhoes == 1 else f"{abaixo_de_mil(milhoes)} milhoes"
        )
    milhares, unidade = divmod(resto, 1000)
    if milhares:
        partes.append("mil" if milhares == 1 else f"{abaixo_de_mil(milhares)} mil")
    if unidade:
        partes.append(abaixo_de_mil(unidade))
    return " e ".join(partes)


class TestExtensoPorPropriedade(unittest.TestCase):
    """A propriedade, e nao uma tabela: `para_int(em_extenso(n)) == n`."""

    def test_ida_e_volta_nos_primeiros_mil(self) -> None:
        for n in range(0, 1001):
            with self.subTest(n=n):
                self.assertEqual(normalizacao.extenso_para_int(_em_extenso(n)), n)

    def test_ida_e_volta_por_amostragem_ate_dois_milhoes(self) -> None:
        """Semente fixa: uma propriedade que falha so as vezes nao se depura."""
        sorteio = random.Random(32)
        for _ in range(2000):
            n = sorteio.randint(0, 2_000_000)
            with self.subTest(n=n):
                self.assertEqual(normalizacao.extenso_para_int(_em_extenso(n)), n)

    def test_ida_e_volta_nas_fronteiras(self) -> None:
        for n in (
            10, 11, 15, 16, 19, 20, 21, 99, 100, 101, 110, 111, 199, 200,
            999, 1000, 1001, 1100, 1999, 2000, 10_000, 100_000, 999_999,
            10**6, 1_000_001, 2_000_000,
        ):
            with self.subTest(n=n):
                self.assertEqual(normalizacao.extenso_para_int(_em_extenso(n)), n)

    def test_as_duas_grafias_dao_o_mesmo(self) -> None:
        """O texto que chega e do modelo; le-se a europeia e a brasileira."""
        for europeu, brasileiro in (
            ("dezasseis", "dezesseis"),
            ("dezassete", "dezessete"),
            ("dezanove", "dezenove"),
            ("catorze", "quatorze"),
        ):
            with self.subTest(par=europeu):
                self.assertEqual(
                    normalizacao.extenso_para_int(europeu),
                    normalizacao.extenso_para_int(brasileiro),
                )

    def test_palavra_que_nao_e_numero_levanta(self) -> None:
        with self.assertRaises(normalizacao.NaoEDinheiroError):
            normalizacao.extenso_para_int("doze camisas")


# ------------------------------------------------------------- o extractor
class TestExtraccao(unittest.TestCase):
    def _linha(self, texto: str, **kw) -> extraccao.Linha:
        (linha,) = extraccao.extrair(texto, **kw)
        return linha

    def test_a_ordem_das_classes(self) -> None:
        """Percentagem antes de data, data antes de dinheiro, dinheiro antes de
        quantidade. Um `10%` lido como dinheiro nunca dava `discount_unbacked`.
        """
        linha = self._linha("10% a 14/11/2026 por 12 500 Kz com 3 unidades")
        self.assertEqual(
            [n.classe for n in linha.numeros],
            ["percentagem", "datahora", "dinheiro", "quantidade"],
        )

    def test_os_digitos_de_um_sku_nao_sao_um_numero(self) -> None:
        linha = self._linha("SKU-123 esta disponivel", skus=("SKU-123",))
        self.assertEqual(linha.numeros, ())
        self.assertEqual(linha.skus, ("SKU-123",))

    def test_os_digitos_de_um_nome_nao_sao_um_numero(self) -> None:
        """O controlo positivo do conjunto adversarial apanhou isto.

        «Vestido 2 pecas» dava `qty_unbacked` em **todas** as respostas sobre
        esse produto — o *renderer* a falhar o seu proprio validador.
        """
        linha = self._linha(
            "SKU-400 - Vestido 2 pecas - 12 500 Kz",
            skus=("SKU-400",),
            nomes=("Vestido 2 pecas",),
        )
        self.assertEqual([n.classe for n in linha.numeros], ["dinheiro"])
        self.assertEqual(linha.nomes, ("Vestido 2 pecas",))

    def test_o_que_nao_se_reconhece_cai_em_outro(self) -> None:
        """*Fail-closed*: o saco de `outro` da `number_unbacked`."""
        linha = self._linha("Ligue para o 923")
        self.assertEqual([n.classe for n in linha.numeros], ["outro"])
        self.assertEqual(linha.numeros[0].valor, 923)

    def test_um_e_artigo_e_nao_numero(self) -> None:
        self.assertEqual(self._linha("Encontrei um produto").numeros, ())
        self.assertEqual(self._linha("Levo um").numeros, ())

    def test_mas_um_com_contagem_e_numero(self) -> None:
        linha = self._linha("Tenho um em stock")
        self.assertEqual([n.classe for n in linha.numeros], ["quantidade"])

    def test_o_extenso_nao_engole_a_marca_de_moeda(self) -> None:
        """Um padrao guloso apanhava «doze mil e quinhentos Kz» com o `Kz`
        dentro, e o numero **desaparecia** — um falso aceite.
        """
        linha = self._linha("doze mil e quinhentos Kz")
        self.assertEqual([n.classe for n in linha.numeros], ["dinheiro"])
        self.assertEqual(linha.numeros[0].value_minor, DOZE_MIL_E_QUINHENTOS)

    def test_o_e_final_nao_fica_dentro_da_corrida(self) -> None:
        linha = self._linha("doze mil e caixas")
        self.assertEqual(linha.numeros[0].bruto, "doze mil")

    def test_uma_linha_por_linha(self) -> None:
        linhas = extraccao.extrair("primeira 1\nsegunda 2\n")
        self.assertEqual(len(linhas), 3)
        self.assertEqual(linhas[2].numeros, ())

    def test_o_marcador_a_partir_de_le_se_sem_acentos(self) -> None:
        self.assertTrue(self._linha("A Partir De 12 500 Kz").tem_a_partir_de)

    def test_classe_invalida_levanta(self) -> None:
        with self.assertRaises(ValueError):
            extraccao.Numero(bruto="1", inicio=0, fim=1, classe="inventada")


# ----------------------------------------------------- os sete veredictos
class _ComCatalogo(unittest.TestCase):
    """Base com o catalogo do conjunto adversarial."""

    def setUp(self) -> None:
        self.facts = ca.facts()
        self.ofertas = ca.OFERTAS

    def validar(self, texto: str, literais: tuple[int, ...] = ()) -> veredicto.Verdict:
        return veredicto.validar(
            texto,
            self.facts,
            veredicto.Policy(allowed_literals=literais),
            self.ofertas,
        )


class TestSeteVeredictos(_ComCatalogo):
    """Um teste por veredicto, e **o controlo positivo ao lado de cada um**.

    A assimetria e o ponto: sem o par, `assertFalse(ok)` passa num validador que
    recusa tudo. Foi o defeito do X-02 do KAM-028, que media onze **recusas** e
    nao onze tools.
    """

    def test_money_unbacked(self) -> None:
        self.assertEqual(
            self.validar("SKU-100 - Camisa Azul - 99 999 Kz").codigos,
            ("money_unbacked",),
        )
        self.assertTrue(self.validar("SKU-100 - Camisa Azul - 12 500 Kz").ok)

    def test_sku_price_mismatch(self) -> None:
        self.assertEqual(
            self.validar("SKU-100 - Camisa Azul - 9 000 Kz").codigos,
            ("sku_price_mismatch",),
        )
        self.assertTrue(self.validar("SKU-200 - Calca Preta - 9 000 Kz").ok)

    def test_name_sku_mismatch(self) -> None:
        self.assertEqual(
            self.validar("SKU-100 - Calca Preta - 12 500 Kz").codigos,
            ("name_sku_mismatch",),
        )
        self.assertTrue(self.validar("SKU-100 - Camisa Azul - 12 500 Kz").ok)

    def test_qty_unbacked(self) -> None:
        self.assertEqual(
            self.validar("SKU-100 - Camisa Azul - 7 unidades").codigos,
            ("qty_unbacked",),
        )
        self.assertTrue(self.validar("SKU-100 - Camisa Azul - 3 unidades").ok)

    def test_datetime_unbacked(self) -> None:
        self.assertEqual(
            self.validar("A entrega e a 20/12/2026").codigos, ("datetime_unbacked",)
        )
        self.assertTrue(self.validar("A entrega e a 14/11/2026").ok)

    def test_discount_unbacked_recusa_sempre(self) -> None:
        """Nao ha `kind` `discount` (divida 105): toda a percentagem recusa.

        **O controlo positivo deste veredicto nao existe**, e e isso que este
        teste registra: nao ha `Fact` que o possa satisfazer, pelo que a metade
        «com *fact* passa» e inverificavel ate o KAM-031 produzir o `kind`.
        """
        for pct in ("10%", "0%", "100%", "5 por cento"):
            with self.subTest(pct=pct):
                self.assertEqual(
                    self.validar(f"Com {pct} de desconto").codigos,
                    ("discount_unbacked",),
                )
        with self.assertRaises(ValueError):
            Fact(fact_id="f", kind="discount", value=10, retrieved_at="z")

    def test_number_unbacked(self) -> None:
        self.assertEqual(
            self.validar("Entregamos em 24 horas").codigos, ("number_unbacked",)
        )
        self.assertTrue(self.validar("Entregamos em 24 horas", literais=(24,)).ok)

    def test_os_sete_e_so_os_sete(self) -> None:
        self.assertEqual(len(veredicto.VEREDICTOS), 7)
        with self.assertRaises(veredicto.VeredictoDesconhecidoError):
            veredicto.Erro("price_mode_mismatch")

    def test_um_verdict_incoerente_levanta(self) -> None:
        with self.assertRaises(ValueError):
            veredicto.Verdict(ok=True, errors=(veredicto.Erro("money_unbacked"),))
        with self.assertRaises(ValueError):
            veredicto.Verdict(ok=False, errors=())

    def test_um_erro_nao_leva_texto(self) -> None:
        """A resposta validada pode repetir texto do cliente (ADR-010).

        O `Erro` tem `codigo`, `valor` e `sku` e mais nada: nao ha campo por onde
        prosa chegue ao registo do servico. E a licao que o `fact_id` do KAM-028
        pagou com canarios.
        """
        campos = set(veredicto.Erro.__dataclass_fields__)
        self.assertEqual(campos, {"codigo", "valor", "sku"})
        canario = "o meu numero e 923456789 e moro na Rua X"
        for erro in self.validar(canario).errors:
            for valor in (erro.codigo, erro.sku):
                self.assertNotIn("923456789", str(valor))
                self.assertNotIn("Rua", str(valor))


class TestVinculoSkuPreco(_ComCatalogo):
    """«Produto errado com preco certo» — o ponto cego que o ADR-007 assinala."""

    def test_o_preco_certo_no_sku_errado_falha(self) -> None:
        for sku, outro in (("SKU-100", "SKU-200"), ("SKU-300", "SKU-400")):
            with self.subTest(sku=sku):
                ver = self.validar(f"{sku} - {ca._nome(sku)} - {ca._kz(ca.PRECOS[outro])}")
                self.assertIn("sku_price_mismatch", ver.codigos)

    def test_um_preco_sem_sku_na_linha_falha(self) -> None:
        """O §6.3 do `docs/tecnica/05`: «resposta com `sku` ausente e rejeitada»."""
        self.assertEqual(
            self.validar("O preco e 12 500 Kz").codigos, ("sku_price_mismatch",)
        )

    def test_o_vinculo_e_por_linha_e_nao_pelo_texto_todo(self) -> None:
        """Duas linhas certas passam; as mesmas cruzadas falham."""
        certo = (
            "SKU-100 - Camisa Azul - 12 500 Kz\n"
            "SKU-200 - Calca Preta - 9 000 Kz"
        )
        self.assertTrue(self.validar(certo).ok)
        cruzado = (
            "SKU-100 - Camisa Azul - 9 000 Kz\n"
            "SKU-200 - Calca Preta - 12 500 Kz"
        )
        self.assertEqual(
            self.validar(cruzado).codigos,
            ("sku_price_mismatch", "sku_price_mismatch"),
        )

    def test_um_total_nao_precisa_de_sku(self) -> None:
        """Um `total` nao tem `sku` (KAM-028), e os totais vem do `propose_cart`."""
        self.assertTrue(self.validar(f"Total: {ca._kz(ca.TOTAL)}").ok)

    def test_um_total_somado_pelo_modelo_falha(self) -> None:
        """Criterio 3: a soma esta certa e **nao e** *fact*."""
        # **Nao o par que faz o `TOTAL`**: 12 500 + 9 000 e exactamente o
        # carrinho do `propose_cart`, e nesse caso a soma **e** *fact* e passa
        # com razao. O que o criterio 3 mede e a soma certa que nao e *fact*.
        soma = ca.PRECOS["SKU-100"] + ca.PRECOS["SKU-300"]
        self.assertNotEqual(soma, ca.TOTAL)
        self.assertEqual(
            self.validar(f"Total: {ca._kz(soma)}").codigos, ("money_unbacked",)
        )


class TestModosDePreco(_ComCatalogo):
    """Criterio 4, e o `precoDisplay` do `docs/tecnica/03` §7.1."""

    def test_a_partir_de_citado_como_fixo_falha(self) -> None:
        self.assertEqual(
            self.validar("SKU-500 - Fato Completo - 5 000 Kz").codigos,
            ("sku_price_mismatch",),
        )

    def test_a_partir_de_com_o_modo_passa(self) -> None:
        self.assertTrue(
            self.validar("SKU-500 - Fato Completo - a partir de 5 000 Kz").ok
        )

    def test_sob_consulta_com_qualquer_numero_falha(self) -> None:
        """Mesmo um valor que coincide com o total do carrinho."""
        for valor in (ca.TOTAL, ca.PRECOS["SKU-100"], 100):
            with self.subTest(valor=valor):
                self.assertEqual(
                    self.validar(f"SKU-600 - Movel por medida - {ca._kz(valor)}").codigos,
                    ("sku_price_mismatch",),
                )

    def test_sob_consulta_sem_numero_passa(self) -> None:
        self.assertTrue(
            self.validar("SKU-600 - Movel por medida - preco sob consulta").ok
        )

    def test_o_display_leva_o_modo(self) -> None:
        self.assertEqual(render.preco_display(1250000, "fixo"), "12 500 Kz")
        self.assertEqual(
            render.preco_display(1250000, "a_partir_de"), "a partir de 12 500 Kz"
        )
        self.assertEqual(
            render.preco_display(1250000, "sob_consulta"), "preco sob consulta"
        )

    def test_sob_consulta_nunca_devolve_numero(self) -> None:
        self.assertFalse(re.search(r"\d", render.preco_display(999, "sob_consulta")))


# --------------------------------------------------------------- o renderer
class TestRenderer(_ComCatalogo):
    def test_os_cinco_blocos(self) -> None:
        self.assertEqual(render.BLOCOS, ("text", "item", "total", "buttons", "datetime"))

    def test_rende_os_cinco(self) -> None:
        out = render.renderizar(
            [
                {"type": "text", "text": "Encontrei estas opcoes para si:"},
                {"type": "item", "sku": "SKU-100", "show": ["name", "price", "stock"]},
                {"type": "total", "fact_id": "ft-1"},
                {"type": "datetime", "fact_id": "fd-1"},
                {"type": "buttons", "ids": ["confirm:c_77", "human"]},
            ],
            self.facts,
            self.ofertas,
        )
        self.assertEqual(
            out.texto,
            "Encontrei estas opcoes para si:\n"
            "SKU-100 - Camisa Azul - 12 500 Kz - 3 unidades\n"
            "Total: 21 500 Kz\n"
            "14/11/2026 as 14h30",
        )
        self.assertEqual(out.botoes, ("confirm:c_77", "human"))

    def test_os_botoes_saiem_ao_lado_e_nao_no_texto(self) -> None:
        """Um `c_77` no corpo dava `number_unbacked`: o *renderer* a falhar o
        seu proprio validador. E e o que o canal faz (`docs/tecnica/01` §8).
        """
        out = render.renderizar(
            [{"type": "buttons", "ids": ["confirm:c_77"]}], self.facts, self.ofertas
        )
        self.assertEqual(out.texto, "")
        self.assertNotIn("77", out.texto)

    def test_um_bloco_text_com_digitos_levanta(self) -> None:
        with self.assertRaises(render.BlocoInvalidoError):
            render.renderizar([{"type": "text", "text": "Custa 12 500 Kz"}])

    def test_um_item_leva_sempre_o_sku(self) -> None:
        """O §6.3: «resposta com `sku` ausente e rejeitada»."""
        out = render.renderizar(
            [{"type": "item", "sku": "SKU-100", "show": ["name"]}],
            self.facts,
            self.ofertas,
        )
        self.assertTrue(out.texto.startswith("SKU-100"))

    def test_item_sem_sku_levanta(self) -> None:
        with self.assertRaises(render.BlocoInvalidoError):
            render.renderizar([{"type": "item", "show": ["name"]}], self.facts, self.ofertas)

    def test_um_campo_que_nao_existe_levanta(self) -> None:
        with self.assertRaises(render.BlocoInvalidoError):
            render.renderizar(
                [{"type": "item", "sku": "SKU-100", "show": ["description"]}],
                self.facts,
                self.ofertas,
            )

    def test_nao_ha_campo_de_descricao(self) -> None:
        """Criterio 5, **estrutural**: os digitos de uma descricao da PME nao
        tem bloco por onde chegar ao cliente.
        """
        self.assertEqual(render.CAMPOS_DE_ITEM, ("name", "price", "stock"))
        self.assertNotIn("description", render.CAMPOS_DE_ITEM)
        self.assertNotIn("descricao", render.Oferta.__dataclass_fields__)

    def test_um_nome_com_preco_dentro_levanta(self) -> None:
        """O que a reserva do intervalo do nome abriria, fechado onde o dado entra."""
        for nome in ("Camisa 99 999 Kz", "Camisa a 12.500", "Promo 50000", "Camisa AOA"):
            with self.subTest(nome=nome):
                with self.assertRaises(render.NomeComPrecoError):
                    render.Oferta(sku="SKU-1", nome=nome, preco_tipo="fixo")

    def test_um_nome_com_digito_nu_passa(self) -> None:
        self.assertEqual(
            render.Oferta(sku="SKU-1", nome="Vestido 2 pecas", preco_tipo="fixo").nome,
            "Vestido 2 pecas",
        )

    def test_um_bloco_desconhecido_levanta(self) -> None:
        with self.assertRaises(render.BlocoInvalidoError):
            render.renderizar([{"type": "image"}])

    def test_sem_fact_levanta_em_vez_de_omitir(self) -> None:
        """Omitir produzia uma mensagem mais curta e plausivel do que a pedida."""
        with self.assertRaises(render.BlocoInvalidoError):
            render.renderizar([{"type": "total", "fact_id": "nao-existe"}], self.facts)
        with self.assertRaises(render.BlocoInvalidoError):
            render.renderizar(
                [{"type": "item", "sku": "SKU-600", "show": ["stock"]}],
                self.facts,
                self.ofertas,
            )

    def test_mais_de_dez_botoes_levanta(self) -> None:
        """Limite da Meta (`docs/tecnica/02` §8.2, CONFIRMADO)."""
        self.assertEqual(render.MAX_BOTOES, 10)
        with self.assertRaises(render.BlocoInvalidoError):
            render.renderizar(
                [{"type": "buttons", "ids": [f"b{i}" for i in range(11)]}],
                self.facts,
                self.ofertas,
            )

    def test_um_modo_de_preco_inventado_levanta(self) -> None:
        with self.assertRaises(ValueError):
            render.Oferta(sku="SKU-1", nome="X", preco_tipo="exato")


class TestApresentacaoDoTempo(unittest.TestCase):
    """UTC no armazenamento, `Africa/Luanda` na apresentacao."""

    def test_luanda_e_utc_mais_uma_hora(self) -> None:
        self.assertEqual(
            render.LUANDA.utcoffset(None), __import__("datetime").timedelta(hours=1)
        )

    def test_o_utc_do_fact_aparece_em_luanda(self) -> None:
        self.assertEqual(
            render.datahora_display("2026-11-14T13:30:00Z"), "14/11/2026 as 14h30"
        )

    def test_a_meia_noite_utc_e_a_uma_em_luanda(self) -> None:
        self.assertEqual(
            render.datahora_display("2026-11-14T00:00:00Z"), "14/11/2026 as 01h00"
        )

    def test_um_instante_sem_fuso_le_se_como_utc(self) -> None:
        self.assertEqual(
            render.datahora_display("2026-11-14T13:30:00"), "14/11/2026 as 14h30"
        )

    def test_as_formas_que_a_camada_2_aceita(self) -> None:
        """O extractor parte «14/11/2026 as 14h30» em dois achados."""
        formas = render.formas_de_datahora("2026-11-14T13:30:00Z")
        self.assertIn("14/11/2026", formas)
        self.assertIn("14h30", formas)


# ------------------------------------------------------------- integracao
class TestIdaEVolta(_ComCatalogo):
    """`compose -> validate -> render` com *facts* de tools falsas.

    **E a propriedade que mais importa deste ticket**: o que a camada 1 escreve
    tem de passar a camada 2. Se nao passasse, cada resposta legitima gastava
    uma repeticao do modelo e acabava em *handoff* — o validador a bloquear a
    loja em vez de a proteger.
    """

    def _blocos_de_tudo(self) -> list[dict]:
        return [
            {"type": "text", "text": "Encontrei estas opcoes para si:"},
            *[
                {"type": "item", "sku": o.sku, "show": ["name", "price", "stock"]}
                for o in self.ofertas
                if o.sku in ca.STOCKS
            ],
            {"type": "item", "sku": "SKU-600", "show": ["name", "price"]},
            {"type": "total", "fact_id": "ft-1"},
            {"type": "datetime", "fact_id": "fd-1"},
            {"type": "buttons", "ids": ["confirm:c_77", "cancel:c_77", "human"]},
        ]

    def test_o_que_o_renderer_escreve_passa_o_validador(self) -> None:
        out = render.renderizar(self._blocos_de_tudo(), self.facts, self.ofertas)
        ver = self.validar(out.texto)
        self.assertTrue(ver.ok, f"o renderer falhou o seu validador: {ver.errors}")

    def test_cada_bloco_sozinho_tambem_passa(self) -> None:
        for bloco in self._blocos_de_tudo():
            with self.subTest(bloco=bloco.get("type"), sku=bloco.get("sku")):
                out = render.renderizar([bloco], self.facts, self.ofertas)
                self.assertTrue(self.validar(out.texto).ok)

    def test_um_fact_trocado_quebra_a_ida_e_volta(self) -> None:
        """O controlo negativo da integracao: sem ele, `assertTrue(ok)` passaria
        num validador que aceita tudo.
        """
        out = render.renderizar(self._blocos_de_tudo(), self.facts, self.ofertas)
        outros = tuple(
            Fact(
                fact_id=f.fact_id,
                kind=f.kind,
                value=f.value + 1 if isinstance(f.value, int) else f.value,
                retrieved_at=f.retrieved_at,
                sku=f.sku,
            )
            for f in self.facts
        )
        ver = veredicto.validar(out.texto, outros, veredicto.Policy(), self.ofertas)
        self.assertFalse(ver.ok)


# ---------------------------------------------------------------- metricas
class TestMetricas(unittest.TestCase):
    def setUp(self) -> None:
        self.metricas = MetricasDoAgr()

    def test_as_cinco_existem(self) -> None:
        self.assertEqual(len(METRICAS_DO_VALIDADOR), 5)
        for metrica in METRICAS_DO_VALIDADOR:
            with self.subTest(metrica=metrica):
                self.metricas.contar(metrica, "vendedor")
        exposicao = self.metricas.exposicao()
        for metrica in METRICAS_DO_VALIDADOR:
            self.assertIn(f'{metrica}{{vertical="vendedor"}} 1', exposicao)

    def test_o_eixo_e_o_vertical(self) -> None:
        self.metricas.contar(METRICA_VALIDATE, "servicos")
        self.assertIn('agr_validate_total{vertical="servicos"}', self.metricas.exposicao())

    def test_o_tenant_id_levanta(self) -> None:
        """Criterio 8: pede `tenant_id` em etiqueta, e a gramatica recusa-o.

        E a razao pela qual a caixa do criterio 8 fica **vazia** — nao se alarga
        a gramatica, e a leitura volta a quem escreveu o criterio (`OBS-I`,
        emenda 1.39, e o mesmo desfecho da divida 54).
        """
        for metrica in METRICAS_DO_VALIDADOR:
            with self.subTest(metrica=metrica):
                with self.assertRaises(EtiquetaInvalida):
                    self.metricas.contar(metrica, "1f3c9a2e-0b7d-4c11-9a62-55e0d3a7b401")

    def test_a_etiqueta_deriva_das_verticais_e_nao_de_uma_lista_literal(self) -> None:
        """A licao do `test_gate11` do KAM-027."""
        for vertical in VERTICAIS:
            with self.subTest(vertical=vertical):
                self.metricas.contar(METRICA_VALIDATE, vertical)
        with self.assertRaises(EtiquetaInvalida):
            self.metricas.contar(METRICA_VALIDATE, "orcamento")

    def test_registar_conta_o_que_o_no_lhe_diz(self) -> None:
        falhou = veredicto.Verdict(
            ok=False, errors=(veredicto.Erro("money_unbacked", valor=1),)
        )
        veredicto.registar(self.metricas, "vendedor", falhou, repetiu=True)
        veredicto.registar(
            self.metricas, "vendedor", falhou, handoff=True
        )
        veredicto.registar(
            self.metricas, "vendedor", veredicto.Verdict(ok=True), so_blocos=True
        )
        lido = self.metricas.ler()
        self.assertEqual(lido[f"{METRICA_VALIDATE}:vendedor"], 3)
        self.assertEqual(lido[f"{METRICA_VALIDATE_FALHAS}:vendedor"], 2)
        self.assertEqual(lido[f"{METRICA_VALIDATE_REPETICOES}:vendedor"], 1)
        self.assertEqual(lido[f"{METRICA_VALIDATE_HANDOFF}:vendedor"], 1)
        self.assertEqual(lido[f"{METRICA_RENDER_ONLY}:vendedor"], 1)

    def test_as_quatro_taxas_do_922_saiem_dos_cinco_contadores(self) -> None:
        """Nao ha histogramas nesta biblioteca (ADR-018): a taxa e uma razao."""
        for _ in range(8):
            veredicto.registar(self.metricas, "vendedor", veredicto.Verdict(ok=True))
        falhou = veredicto.Verdict(ok=False, errors=(veredicto.Erro("money_unbacked"),))
        veredicto.registar(self.metricas, "vendedor", falhou, repetiu=True)
        veredicto.registar(self.metricas, "vendedor", falhou, handoff=True)
        lido = self.metricas.ler()
        total = lido[f"{METRICA_VALIDATE}:vendedor"]
        self.assertEqual(total, 10)
        validate_fail_rate = (
            lido[f"{METRICA_VALIDATE_FALHAS}:vendedor"]
        ) / total
        self.assertAlmostEqual(validate_fail_rate, 0.2)
        validate_retry_rate = lido[f"{METRICA_VALIDATE_REPETICOES}:vendedor"] / total
        self.assertAlmostEqual(validate_retry_rate, 0.1)
        self.assertEqual(lido[f"{METRICA_VALIDATE_HANDOFF}:vendedor"], 1)


# ------------------------------------------------------- o gate adversarial
class TestConjuntoAdversarial(unittest.TestCase):
    """Criterio 2: >= 200 casos, **0** falsos aceites — com controlo positivo.

    A regra dos tres fica escrita onde o resultado aparece: 0 falhas em N = 200
    limita o risco a cerca de **1,5%** (95%), e nao a zero. «0 divergentes neste
    conjunto» nao e «0 divergentes em producao», que o §9.2 chama «objectivo de
    desenho com risco residual» medido por amostragem (`citation_fail_rate`).
    """

    def setUp(self) -> None:
        self.facts = ca.facts()

    def _validar(self, caso: ca.Caso) -> veredicto.Verdict:
        return veredicto.validar(
            caso.texto,
            self.facts,
            veredicto.Policy(allowed_literals=caso.literais),
            ca.OFERTAS,
        )

    def test_o_conjunto_tem_pelo_menos_duzentos_casos(self) -> None:
        self.assertGreaterEqual(len(ca.CONJUNTO), 200, len(ca.CONJUNTO))

    def test_zero_falsos_aceites(self) -> None:
        falharam = [c.nome for c in ca.DEVE_RECUSAR if self._validar(c).ok]
        self.assertEqual(falharam, [], f"{len(falharam)} falso(s) aceite(s)")

    def test_cada_recusa_pela_razao_certa(self) -> None:
        """Um conjunto que recusasse tudo pela razao errada dava «0 falsos
        aceites» e nao valia nada. Cada caso diz **qual** veredicto espera.
        """
        erradas = []
        for caso in ca.DEVE_RECUSAR:
            codigos = set(self._validar(caso).codigos)
            if not set(caso.espera) <= codigos:
                erradas.append((caso.nome, caso.espera, sorted(codigos)))
        self.assertEqual(erradas, [])

    def test_zero_falsos_rejeitos_no_controlo_positivo(self) -> None:
        """Sem isto, a *suite* passava sobre um validador que recusa a loja toda."""
        recusados = [
            (c.nome, self._validar(c).codigos)
            for c in ca.DEVE_ACEITAR
            if not self._validar(c).ok
        ]
        self.assertEqual(recusados, [])

    def test_o_controlo_positivo_nao_e_simbolico(self) -> None:
        self.assertGreaterEqual(len(ca.DEVE_ACEITAR), 40, len(ca.DEVE_ACEITAR))

    def test_os_sete_veredictos_estao_todos_cobertos(self) -> None:
        cobertos = {codigo for c in ca.DEVE_RECUSAR for codigo in c.espera}
        self.assertEqual(cobertos, set(veredicto.VEREDICTOS))

    def test_as_sete_familias_do_criterio_2(self) -> None:
        familias = {c.familia for c in ca.DEVE_RECUSAR}
        for esperada in (
            "dinheiro sem fact",
            "par sku<->preco trocado",
            "nome resolve para outro sku",
            "quantidade sem fact",
            "data/hora sem fact",
            "percentagem sem fact discount",
            "numero solto",
        ):
            with self.subTest(familia=esperada):
                self.assertIn(esperada, familias)


class TestLimitesAssumidos(unittest.TestCase):
    """As limitacoes do §9.2: **medidas**, e nao fechadas por este ticket.

    O bloco manda «limitacoes a assumir e testar». Um validador que passasse
    estas nao e o que o ticket pede; o que ele pede e que estejam nomeadas e com
    o seu efeito preso por teste — no dia em que uma delas mudar, isto falha e
    alguem decide de proposito.
    """

    def setUp(self) -> None:
        self.facts = ca.facts()

    def test_os_limites_passam_hoje_e_estao_nomeados(self) -> None:
        for caso in ca.LIMITES:
            with self.subTest(limite=caso.nome):
                ver = veredicto.validar(
                    caso.texto, self.facts, veredicto.Policy(), ca.OFERTAS
                )
                self.assertTrue(ver.ok, f"{caso.nome} passou a recusar: {ver.errors}")

    def test_os_limites_nao_entram_no_gate_duro(self) -> None:
        """Sao lista separada de proposito: inflavam o «0 falsos aceites»."""
        nomes = {c.nome for c in ca.CONJUNTO}
        for caso in ca.LIMITES:
            self.assertNotIn(caso.nome, nomes)

    def test_as_familias_do_922_estao_representadas(self) -> None:
        familias = " ".join(c.familia for c in ca.LIMITES)
        for tema in (
            "coincidencia de valores",
            "numeros por extenso",
            "afirmacoes sem numeros",
            "disponibilidade qualitativa",
            "facts obsoletos entre turnos",
        ):
            with self.subTest(tema=tema):
                self.assertIn(tema, familias)

    def test_o_retrieved_at_nao_e_consultado_por_este_validador(self) -> None:
        """Quem revalida e o `cart_build`/`create_order` (§9.2), nao isto."""
        antigo = tuple(
            Fact(
                fact_id=f.fact_id,
                kind=f.kind,
                value=f.value,
                retrieved_at="1999-01-01T00:00:00Z",
                sku=f.sku,
            )
            for f in self.facts
        )
        ver = veredicto.validar(
            "SKU-100 - Camisa Azul - 12 500 Kz", antigo, veredicto.Policy(), ca.OFERTAS
        )
        self.assertTrue(ver.ok)


# -------------------------------------------------------------------- canon
class TestCanon(unittest.TestCase):
    """Os nomes deste modulo sao os do dicionario §3.30 (emenda 1.39).

    Uma lista em codigo e uma lista no canon divergem em silencio; e o defeito
    que o §1 do dicionario declara e que esta bateria impede.
    """

    def setUp(self) -> None:
        self.dicionario = (
            _RAIZ / "specs/02_Dicionario_de_Dados_Canonico.md"
        ).read_text(encoding="utf-8")

    def test_os_sete_veredictos_estao_no_dicionario(self) -> None:
        for codigo in veredicto.VEREDICTOS:
            with self.subTest(codigo=codigo):
                self.assertIn(f"`{codigo}`", self.dicionario)

    def test_os_cinco_blocos_estao_no_dicionario(self) -> None:
        self.assertIn("`blocks[].type`", self.dicionario)
        for bloco in render.BLOCOS:
            with self.subTest(bloco=bloco):
                self.assertIn(f"`{bloco}`", self.dicionario)

    def test_as_cinco_metricas_estao_no_dicionario(self) -> None:
        for metrica in METRICAS_DO_VALIDADOR:
            with self.subTest(metrica=metrica):
                self.assertIn(f"`{metrica}{{vertical}}`", self.dicionario)

    def test_o_value_minor_e_canon_e_o_value_kz_e_variante(self) -> None:
        self.assertIn("`value_minor`", self.dicionario)
        self.assertIn("### 3.30", self.dicionario)

    def test_a_emenda_139_esta_no_controlo_de_versoes(self) -> None:
        self.assertIn("| 1.39 | Outubro 2026 |", self.dicionario)
        self.assertIn("| Versão | 1.39 — **PROPOSTA**", self.dicionario)

    def test_os_tres_kind_que_faltam_tem_credor_escrito(self) -> None:
        dividas = (_RAIZ / "docs/dividas-documentais.md").read_text(encoding="utf-8")
        for kind in ("`name`", "`qty`", "`discount`"):
            with self.subTest(kind=kind):
                self.assertIn(kind, dividas)
        self.assertIn("KAM-031", dividas)

    def test_o_artefacto_comportamental_tem_semver(self) -> None:
        """DoD «Eval-gate». Quem o le e o *gate* 13 do KAM-040."""
        import kamba_agr.validador as modulo

        self.assertRegex(modulo.VERSAO, r"^\d+\.\d+\.\d+$")

    def test_o_init_nao_importa_modulos_do_pacote(self) -> None:
        """Quem quer o validador importa o modulo, nao o pacote.

        **Le-se a fonte e nao os atributos**: assim que qualquer bateria faz
        `import kamba_agr.validador.veredicto`, o Python poe o submodulo como
        atributo do pacote, pelo que um `hasattr` daqui dava `True` sempre —
        media a ordem dos testes e nao o `__init__`. Medido: a primeira versao
        deste teste falhava com os quatro.
        """
        import kamba_agr.validador as modulo

        fonte = Path(modulo.__file__).read_text(encoding="utf-8")
        corpo = fonte.split('"""', 2)[2] if fonte.count('"""') >= 2 else fonte
        self.assertNotIn("from .", corpo)
        self.assertNotIn("import .", corpo)
        self.assertIn("from typing import Final", corpo)

    def test_os_modos_de_preco_sao_os_do_dicionario(self) -> None:
        self.assertEqual(
            render.MODOS_DE_PRECO, ("fixo", "a_partir_de", "sob_consulta")
        )
        self.assertIn(
            "`preco_tipo` ∈ {`fixo`, `a_partir_de`, `sob_consulta`}", self.dicionario
        )


class TestGateDeCobertura(unittest.TestCase):
    """O caminho do modulo bate no estrato `critico` do `ci/thresholds.yaml`.

    O criterio 7 pede «cobertura de linhas do modulo >= 90%». O estrato `critico`
    e o unico mecanismo que impoe 90%, e tem `*/validador/*` escrito para «os
    tickets que os vao criar». Uma pasta chamada `validacao/` deixava o padrao
    sem bater e a caixa sem gate — **este teste e o que impede essa renomeacao
    silenciosa**.
    """

    def test_a_pasta_chama_se_validador(self) -> None:
        import kamba_agr.validador as modulo

        caminho = Path(modulo.__file__).parent
        self.assertEqual(caminho.name, "validador")

    def test_o_padrao_do_estrato_critico_bate_nos_ficheiros(self) -> None:
        import fnmatch

        limiares = (_RAIZ / "ci/thresholds.yaml").read_text(encoding="utf-8")
        self.assertIn('- "*/validador/*"', limiares)
        for nome in ("extraccao", "normalizacao", "render", "veredicto"):
            caminho = f"services/agr/src/kamba_agr/validador/{nome}.py"
            with self.subTest(ficheiro=nome):
                self.assertTrue(fnmatch.fnmatch(caminho, "*/validador/*"))

    def test_o_estrato_critico_exige_noventa(self) -> None:
        limiares = (_RAIZ / "ci/thresholds.yaml").read_text(encoding="utf-8")
        bloco = limiares.split("- nome: critico", 1)[1].split("- nome:", 1)[0]
        self.assertIn("minimo_linhas: 90", bloco)


if __name__ == "__main__":
    unittest.main()
