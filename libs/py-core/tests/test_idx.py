"""`kamba_core.idx` sem base de dados (KAM-061).

O comportamento contra o PostgreSQL mede-se em `db/tests_produtos/test_indice.py`.
Aqui fica o que e funcao pura ou contrato com o cliente SQL: a normalizacao, o
*lint* do texto de embedding (criterio 4, tres casos negativos e mais), a forma
das chamadas da camada de resposta e o encaminhamento do consumidor.
"""

from __future__ import annotations

import datetime
import unittest
import uuid

from kamba_core.eventos.consumo import Resultado
from kamba_core.idx import consumidor, pesquisa, texto


class TestNormalizar(unittest.TestCase):
    def test_minusculas_sem_acentos_sem_pontuacao(self) -> None:
        self.assertEqual(texto.normalizar("  Frigorífico LG, 250 L!  "), "frigorifico lg 250 l")

    def test_nfkc_antes_de_tudo(self) -> None:
        # O «ﬁ» (U+FB01) decompoe-se em «fi» pelo NFKC.
        self.assertEqual(texto.normalizar("ﬁltro"), "filtro")

    def test_vazio_fica_vazio(self) -> None:
        self.assertEqual(texto.normalizar("¿?!"), "")

    def test_os_algarismos_nao_entram_na_expansao(self) -> None:
        """Passo 3 do §5.1: um numero e restricao, nao termo do indice."""
        self.assertEqual(
            texto.consulta("quero 2 bicicletas"),
            texto.Consulta(q_norm="quero 2 bicicletas", q_or="quero or bicicletas"),
        )
        self.assertEqual(texto.consulta("250").q_or, "")

    def test_consulta_expande_com_or_sem_repetidos(self) -> None:
        self.assertEqual(
            texto.consulta("Nike Air, nike"),
            texto.Consulta(q_norm="nike air nike", q_or="nike or air"),
        )


class TestTextoDeEmbedding(unittest.TestCase):
    """Criterio 4, a metade do texto: os tres casos negativos do bloco, e mais."""

    def test_os_tres_negativos_do_criterio(self) -> None:
        casos = {
            "Arroz agulha 5 kg por 2500 kz": ("dinheiro",),
            "Telemovel com stock limitado": ("stock",),
            "Sapatilhas, preço especial, disponível hoje": ("disponivel", "preco"),
        }
        for frase, motivos in casos.items():
            with self.subTest(frase=frase):
                with self.assertRaises(texto.TextoDeEmbeddingProibido) as erro:
                    texto.exigir_texto_de_embedding(frase)
                self.assertEqual(erro.exception.motivos, motivos)

    def test_todas_as_formas_de_dinheiro(self) -> None:
        for frase in ("500kz", "500 KZ", "1.500,00 akz", "20$", "$ 20", "custa 3 AKZ"):
            with self.subTest(frase=frase):
                self.assertEqual(texto.motivos_de_recusa(frase), ("dinheiro",))

    def test_sem_acento_tambem_recusa(self) -> None:
        self.assertEqual(texto.motivos_de_recusa("preco e disponivel"), ("disponivel", "preco"))

    def test_o_que_nao_e_dinheiro_passa(self) -> None:
        """Algarismos sem moeda (a unidade do produto) e palavras parecidas."""
        for frase in (
            "Frigorifico LG 250 L",
            "Televisor 55 polegadas",
            "Kit de stockings de algodao",
            "Precioso perfume floral",
            "kz",
        ):
            with self.subTest(frase=frase):
                self.assertEqual(texto.exigir_texto_de_embedding(frase), frase)

    def test_a_mensagem_nao_repete_o_texto(self) -> None:
        with self.assertRaises(texto.TextoDeEmbeddingProibido) as erro:
            texto.exigir_texto_de_embedding("Segredo da loja 900 kz")
        self.assertNotIn("Segredo", str(erro.exception))


class _Cursor:
    def __init__(self, ligacao: "_Ligacao") -> None:
        self.ligacao = ligacao

    def execute(self, sql: str, parametros=()) -> None:
        self.ligacao.chamadas.append((sql, tuple(parametros)))

    def fetchone(self):
        return ("x",)

    def fetchall(self):
        return self.ligacao.linhas

    def close(self) -> None:
        pass


class _Ligacao:
    autocommit = False

    def __init__(self, linhas=()) -> None:
        self.linhas = list(linhas)
        self.chamadas: list[tuple[str, tuple]] = []
        self.confirmada = False

    def cursor(self) -> _Cursor:
        return _Cursor(self)

    def commit(self) -> None:
        self.confirmada = True

    def rollback(self) -> None:
        pass


class TestPesquisar(unittest.TestCase):
    TENANT = str(uuid.uuid4())

    def test_a_consulta_nao_tem_parametro_de_tenant(self) -> None:
        """O tenant da resposta e o do contexto, e so o do contexto."""
        self.assertEqual(pesquisa.SQL_RESPOSTA.count("current_setting('app.tenant_id', true)"), 2)
        ligacao = _Ligacao()
        pesquisa.pesquisar(ligacao, self.TENANT, "arroz agulha")
        sql, parametros = ligacao.chamadas[-1]
        self.assertIs(sql, pesquisa.SQL_RESPOSTA)
        self.assertEqual(parametros, ("arroz agulha", "arroz or agulha", None, None, None))
        self.assertNotIn(self.TENANT, parametros)
        # O contexto foi posto pelo `tenant_guard`, primeira instrucao.
        self.assertIn(self.TENANT, ligacao.chamadas[0][1])
        self.assertTrue(ligacao.confirmada)

    def test_o_limiar_e_local_a_transaccao(self) -> None:
        ligacao = _Ligacao()
        pesquisa.pesquisar(ligacao, self.TENANT, "arroz", limiar=0.5)
        self.assertEqual(ligacao.chamadas[1], (pesquisa.SQL_LIMIAR, ("0.5",)))
        self.assertIn(", true)", pesquisa.SQL_LIMIAR)

    def test_o_vector_vai_em_texto_e_o_preco_duas_vezes(self) -> None:
        ligacao = _Ligacao()
        pesquisa.pesquisar(ligacao, self.TENANT, "arroz", qvec=(1, 0.5), max_preco_minor=100)
        self.assertEqual(ligacao.chamadas[-1][1][2:], ("[1.0,0.5]", 100, 100))

    def test_o_preco_e_unidade_menor_inteira(self) -> None:
        for errado in (1.5, "100", True):
            with self.subTest(valor=errado):
                with self.assertRaises(TypeError):
                    pesquisa.pesquisar(_Ligacao(), self.TENANT, "arroz", max_preco_minor=errado)

    def test_pergunta_vazia_nao_consulta(self) -> None:
        ligacao = _Ligacao()
        self.assertEqual(pesquisa.pesquisar(ligacao, self.TENANT, "?!"), ())
        self.assertNotIn(pesquisa.SQL_RESPOSTA, [sql for sql, _ in ligacao.chamadas])

    def test_sem_tenant_recusa_antes_da_base(self) -> None:
        ligacao = _Ligacao()
        with self.assertRaises(Exception):
            pesquisa.pesquisar(ligacao, None, "arroz")
        self.assertEqual(ligacao.chamadas, [])

    def test_a_linha_sai_no_contrato(self) -> None:
        lido = datetime.datetime(2026, 11, 10, 12, tzinfo=datetime.timezone.utc)
        ligacao = _Ligacao([("arroz", "arroz", "Arroz", 1250000, "fixo", lido, 0.01)])
        (linha,) = pesquisa.pesquisar(ligacao, self.TENANT, "arroz")
        self.assertEqual(tuple(linha), pesquisa.CAMPOS_DO_CONTRATO)
        self.assertEqual(
            linha,
            {
                "sku": "arroz",
                "product_ref": "arroz",
                "nome": "Arroz",
                "preco_minor": 1250000,
                "preco_tipo": "fixo",
                "disponivel": None,
                "fonte": "registo",
                "lido_em": "2026-11-10T12:00:00+00:00",
            },
        )

    def test_candidatos_traz_o_score_e_o_tecto(self) -> None:
        lido = "2026-11-10T12:00:00+00:00"
        ligacao = _Ligacao([("a", "a", "A", 1, "fixo", lido, 0.008)])
        ((linha, score),) = pesquisa.candidatos(ligacao, self.TENANT, "a", tecto_ms=1500)
        self.assertEqual((linha["sku"], score), ("a", 0.008))
        self.assertNotIn("score", linha)
        self.assertIn((pesquisa.SQL_TECTO, ("1500",)), ligacao.chamadas)

    def test_sem_tecto_nao_se_toca_no_statement_timeout(self) -> None:
        ligacao = _Ligacao()
        pesquisa.candidatos(ligacao, self.TENANT, "a")
        self.assertNotIn(pesquisa.SQL_TECTO, [sql for sql, _ in ligacao.chamadas])

    def test_a_linha_aceita_mapas(self) -> None:
        ligacao = _Ligacao(
            [
                {
                    "sku": "a",
                    "product_ref": "a",
                    "nome": "A",
                    "preco_minor": None,
                    "preco_tipo": "sob_consulta",
                    "lido_em": "agora",
                    "o_score": 0.01,
                }
            ]
        )
        (linha,) = pesquisa.pesquisar(ligacao, self.TENANT, "a")
        self.assertEqual((linha["preco_minor"], linha["lido_em"]), (None, "agora"))


class _Bd:
    """O `ClienteSql`: responde ao SQL conhecido e regista o resto."""

    def __init__(self, oferta=None, duplicado: bool = False) -> None:
        self.oferta = oferta
        self.duplicado = duplicado
        self.chamadas: list[tuple[str, tuple]] = []

    def executar(self, sql: str, parametros=()) -> Resultado:
        self.chamadas.append((sql, tuple(parametros)))
        if "INSERT INTO platform.events_consumed" in sql:
            return Resultado(contagem=0 if self.duplicado else 1)
        if sql is consumidor.SQL_LER_OFERTA:
            return Resultado(linhas=(self.oferta,) if self.oferta else ())
        return Resultado(contagem=1)

    def sqls(self) -> list[str]:
        return [sql for sql, _ in self.chamadas]


def _envelope(tipo: str, payload: dict) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "tipo": tipo,
        "tenant_id": str(uuid.uuid4()),
        "agregado": {"tipo": "product", "id": "p", "seq": 1},
        "payload": payload,
    }


class TestConsumidor(unittest.TestCase):
    def test_produto_escreve_o_documento_normalizado(self) -> None:
        bd = _Bd(oferta={"nome": "Frigorífico LG", "publicado": True})
        resultado = consumidor.consumir_evento(
            bd, _envelope("catalog.product_changed", {"sku": "g1", "estado": "publicado"})
        )
        self.assertEqual(resultado.desfecho, "aplicado")
        self.assertIn(
            (consumidor.SQL_ESCREVER_DOCUMENTO, ("g1", 1, "frigorifico lg", True)), bd.chamadas
        )

    def test_produto_sem_oferta_esconde(self) -> None:
        bd = _Bd(oferta=None)
        consumidor.consumir_evento(
            bd, _envelope("catalog.product_changed", {"sku": "g1", "estado": "arquivado"})
        )
        self.assertIn((consumidor.SQL_ESCONDER_DOCUMENTO, ("g1",)), bd.chamadas)
        self.assertNotIn(consumidor.SQL_ESCREVER_DOCUMENTO, bd.sqls())

    def test_os_quatro_eventos_do_tenant_releem_o_tenant(self) -> None:
        for tipo in consumidor.EVENTOS_DO_TENANT:
            with self.subTest(tipo=tipo):
                bd = _Bd()
                consumidor.consumir_evento(bd, _envelope(tipo, {}))
                self.assertIn(consumidor.SQL_RELER_TENANT, bd.sqls())

    def test_duplicado_nao_toca_no_indice(self) -> None:
        bd = _Bd(oferta={"nome": "x", "publicado": True}, duplicado=True)
        resultado = consumidor.consumir_evento(
            bd, _envelope("catalog.product_changed", {"sku": "g1", "estado": "publicado"})
        )
        self.assertEqual(resultado.desfecho, "duplicado")
        self.assertNotIn(consumidor.SQL_LER_OFERTA, bd.sqls())

    def test_tipo_nao_subscrito_levanta_antes_da_base(self) -> None:
        bd = _Bd()
        with self.assertRaises(consumidor.TipoNaoSubscrito):
            consumidor.consumir_evento(bd, _envelope("order.created", {}))
        self.assertEqual(bd.chamadas, [])

    def test_o_efeito_recusa_tipo_desconhecido(self) -> None:
        with self.assertRaises(consumidor.TipoNaoSubscrito):
            consumidor.efeito(_Bd(), {"tipo": "stock.low"})

    def test_produto_sem_sku_falha_e_desfaz(self) -> None:
        bd = _Bd()
        with self.assertRaises(ValueError):
            consumidor.consumir_evento(bd, _envelope("catalog.product_changed", {"estado": "x"}))
        self.assertEqual(bd.sqls()[-1], "ROLLBACK")


if __name__ == "__main__":
    unittest.main()
