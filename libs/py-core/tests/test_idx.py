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
from kamba_core.idx import consumidor, lexico, pesquisa, texto


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
    """Responde as tres leituras do lexico (KAM-062) e devolve o resto da ligacao."""

    def __init__(self, ligacao: "_Ligacao") -> None:
        self.ligacao = ligacao
        self.ultima = ""
        self.description: list[tuple[str]] = []

    def execute(self, sql: str, parametros=()) -> None:
        self.ligacao.chamadas.append((sql, tuple(parametros or ())))
        self.ultima = sql

    def fetchone(self):
        return ("x",)

    def fetchall(self):
        if self.ultima is lexico.SQL_LER_VERSOES:
            self.description = [("versao",), ("versao_do_indice",)]
            return [(1, 1)]
        if self.ultima is lexico.SQL_LER_LEXICO:
            self.description = [("tenant_id",), ("tipo",), ("termo",), ("canonico",), ("peso",)]
            return list(self.ligacao.lexico)
        if self.ultima is lexico.SQL_LER_VOCABULARIO:
            self.description = [("palavra",), ("frequencia",)]
            return []
        return self.ligacao.linhas

    def close(self) -> None:
        pass


class _Ligacao:
    autocommit = False

    def __init__(self, linhas=(), lexico=()) -> None:
        self.linhas = list(linhas)
        self.lexico = list(lexico)
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
        self.assertEqual(
            parametros, ("arroz agulha", "arroz or agulha", None, None, None, None, None, None)
        )
        self.assertNotIn(self.TENANT, parametros)
        # O contexto foi posto pelo `tenant_guard`, primeira instrucao.
        self.assertIn(self.TENANT, ligacao.chamadas[0][1])
        self.assertTrue(ligacao.confirmada)

    def test_a_resposta_ao_cliente_continua_a_ser_de_tres(self) -> None:
        """KAM-064: o `limite` e da avaliacao; sem ele, o `SQL_RESPOSTA` e o mesmo objecto."""
        self.assertIs(pesquisa.sql_resposta(), pesquisa.SQL_RESPOSTA)
        self.assertIn("LIMIT 3\n", pesquisa.SQL_RESPOSTA)
        ligacao = _Ligacao()
        pesquisa.procurar(ligacao, self.TENANT, "arroz")
        self.assertIs(ligacao.chamadas[-1][0], pesquisa.SQL_RESPOSTA)

    def test_a_avaliacao_pede_dez_pela_mesma_consulta(self) -> None:
        dez = pesquisa.sql_resposta(10)
        self.assertEqual(dez, pesquisa.SQL_RESPOSTA.replace("LIMIT 3\n", "LIMIT 10\n"))
        self.assertNotIn("LIMIT 3", dez)
        ligacao = _Ligacao()
        pesquisa.procurar(ligacao, self.TENANT, "arroz", limite=10)
        self.assertEqual(ligacao.chamadas[-1][0], dez)

    def test_o_limite_e_um_inteiro_ate_ao_p_k(self) -> None:
        for errado in (0, 41, True, 2.0, "10"):
            with self.subTest(limite=errado):
                with self.assertRaises(ValueError):
                    pesquisa.sql_resposta(errado)

    def test_o_limiar_e_local_a_transaccao(self) -> None:
        ligacao = _Ligacao()
        pesquisa.pesquisar(ligacao, self.TENANT, "arroz", limiar=0.5)
        self.assertIn((pesquisa.SQL_LIMIAR, ("0.5",)), ligacao.chamadas)
        self.assertIn(", true)", pesquisa.SQL_LIMIAR)

    def test_o_vector_vai_em_texto_e_o_preco_duas_vezes(self) -> None:
        ligacao = _Ligacao()
        pesquisa.pesquisar(ligacao, self.TENANT, "arroz", qvec=(1, 0.5), max_preco_minor=100)
        self.assertEqual(ligacao.chamadas[-1][1][2:5], ("[1.0,0.5]", 100, 100))

    def test_as_restricoes_do_cliente_filtram_a_oferta_viva(self) -> None:
        """KAM-062: o preco dito sai do texto e vai para o filtro, nunca ao indice."""
        ligacao = _Ligacao()
        procura = pesquisa.procurar(ligacao, self.TENANT, "geleira entre 100 e 150 mil")
        sql, parametros = ligacao.chamadas[-1]
        self.assertIs(sql, pesquisa.SQL_RESPOSTA)
        self.assertEqual(parametros[:2], ("geleira", "geleira"))
        self.assertEqual(parametros[3:], (15_000_000, 15_000_000, 10_000_000, 10_000_000, None))
        self.assertEqual(procura.normalizacao.restricoes.min_preco_minor, 10_000_000)

    def test_o_tecto_mais_apertado_ganha(self) -> None:
        ligacao = _Ligacao()
        pesquisa.procurar(ligacao, self.TENANT, "geleira ate 250 mil", max_preco_minor=100)
        self.assertEqual(ligacao.chamadas[-1][1][3:5], (100, 100))
        ligacao = _Ligacao()
        pesquisa.procurar(ligacao, self.TENANT, "geleira ate 1 mil", max_preco_minor=10**9)
        self.assertEqual(ligacao.chamadas[-1][1][3:5], (100_000, 100_000))

    def test_o_alvo_so_ordena(self) -> None:
        ligacao = _Ligacao()
        pesquisa.procurar(ligacao, self.TENANT, "geleira 250 mil")
        self.assertEqual(ligacao.chamadas[-1][1][3:], (None, None, None, None, 25_000_000))

    def test_moeda_estrangeira_nao_filtra(self) -> None:
        ligacao = _Ligacao()
        procura = pesquisa.procurar(ligacao, self.TENANT, "iphone ate 300 dolares")
        self.assertEqual(ligacao.chamadas[-1][1][3:], (None,) * 5)
        self.assertEqual(procura.normalizacao.restricoes.moeda, "USD")

    def test_o_lexico_do_tenant_entra_na_pergunta(self) -> None:
        tenant = str(uuid.uuid4())
        ligacao = _Ligacao(lexico=[(None, "sinonimo", "geleira", "frigorifico", 0.8)])
        pesquisa.procurar(ligacao, tenant, "quero geleira", cache=lexico.Cache())
        self.assertEqual(ligacao.chamadas[-1][1][1], "quero or geleira or frigorifico")

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

    def __init__(self, oferta=None, duplicado: bool = False, lexico=(), versoes=(1, 1),
                 desactualizados=()) -> None:
        self.oferta = oferta
        self.duplicado = duplicado
        self.lexico = tuple(lexico)
        self.versoes = versoes
        self.desactualizados = list(desactualizados)
        self.chamadas: list[tuple[str, tuple]] = []

    def executar(self, sql: str, parametros=()) -> Resultado:
        self.chamadas.append((sql, tuple(parametros)))
        if "INSERT INTO platform.events_consumed" in sql:
            return Resultado(contagem=0 if self.duplicado else 1)
        if sql is consumidor.SQL_LER_OFERTA:
            return Resultado(linhas=(self.oferta,) if self.oferta else ())
        if sql is lexico.SQL_LER_VERSOES:
            versao, do_indice = self.versoes
            return Resultado(linhas=({"versao": versao, "versao_do_indice": do_indice},))
        if sql is lexico.SQL_LER_LEXICO:
            return Resultado(linhas=self.lexico)
        if sql is consumidor.SQL_LER_OFERTAS:
            return Resultado(linhas=tuple(
                {"product_ref": ref, **self.oferta} for ref in parametros[0]
            ) if self.oferta else ())
        if sql is consumidor.SQL_DESACTUALIZADOS:
            limite = parametros[1]
            lote, self.desactualizados = self.desactualizados[:limite], self.desactualizados[limite:]
            return Resultado(linhas=tuple({"product_ref": ref} for ref in lote))
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
            (consumidor.SQL_ESCREVER_DOCUMENTO, (1, "g1", "frigorifico lg", None, True)),
            bd.chamadas,
        )

    def test_produto_sem_oferta_esconde(self) -> None:
        bd = _Bd(oferta=None)
        consumidor.consumir_evento(
            bd, _envelope("catalog.product_changed", {"sku": "g1", "estado": "arquivado"})
        )
        self.assertIn((consumidor.SQL_ESCONDER_DOCUMENTO, ("g1",)), bd.chamadas)
        self.assertNotIn(consumidor.SQL_ESCREVER_DOCUMENTO, bd.sqls())

    def test_o_documento_leva_marca_e_unidade_do_lexico_e_a_versao_corrente(self) -> None:
        """KAM-062: o lado do indice sao os passos 1, 4 e 5, com a versao de agora."""
        linhas = (
            {"tenant_id": None, "tipo": "marca", "termo": "i phone", "canonico": "iphone"},
            {"tenant_id": None, "tipo": "unidade", "termo": "giga", "canonico": "gb"},
            {"tenant_id": None, "tipo": "sinonimo", "termo": "celular", "canonico": "telemovel"},
        )
        bd = _Bd(oferta={"nome": "I Phone 13 128 Giga", "publicado": True}, lexico=linhas,
                 versoes=(9, 4))
        consumidor.consumir_evento(
            bd, _envelope("catalog.product_changed", {"sku": "g1", "estado": "publicado"})
        )
        self.assertIn(
            (consumidor.SQL_ESCREVER_DOCUMENTO, (9, "g1", "iphone 13 128 gb", "iphone", True)),
            bd.chamadas,
        )

    def test_reindexar_reescreve_os_marcados_pela_versao_do_indice(self) -> None:
        bd = _Bd(oferta={"nome": "Geleira LG", "publicado": True}, versoes=(9, 4),
                 desactualizados=["a", "b", "c"])
        self.assertEqual(consumidor.reindexar(bd, str(uuid.uuid4()), lote=2), 2)
        # A versao do indice (4), e nao a corrente (9), escolhe os marcados.
        self.assertIn((consumidor.SQL_DESACTUALIZADOS, (4, 2)), bd.chamadas)
        # Uma escrita so para o lote, com a versao corrente (9) a cabeca.
        escritos = [p for sql, p in bd.chamadas if sql == consumidor.sql_escrever_documentos(2)]
        self.assertEqual(
            escritos, [(9, "a", "geleira lg", None, True, "b", "geleira lg", None, True)]
        )
        self.assertEqual(consumidor.reindexar(bd, str(uuid.uuid4()), lote=2), 1)
        self.assertEqual(consumidor.reindexar(bd, str(uuid.uuid4()), lote=2), 0)

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
