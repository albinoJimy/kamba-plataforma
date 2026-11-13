"""Embeddings do catalogo e da pergunta, sem base de dados (KAM-063).

A porta e a real do KAM-069 (`PortaSobreDestinos`), com o leitor injectado e o
relogio da porta fixo: o que se mede e a ligacao do *gate* a cada chamada, e
nao uma porta falsa que concorde com o ensaio. O fornecedor e falso e tem
contador — e o «contador do *mock*» do criterio 1. O SQL dos documentos e da
oferta corre contra um PostgreSQL no `db/tests_produtos/test_indice.py`
(`TestEmbeddings`).
"""

from __future__ import annotations

import math
import re
import threading
import time
import unittest
from collections.abc import Sequence

from kamba_core.destinos import ESTADO_AUTORIZADO, PortaSobreDestinos
from kamba_core.eventos.consumo import Resultado
from kamba_core.idx import consumidor, embeddings, metricas, texto
from kamba_core.idx.embeddings import (
    DIMENSAO,
    ClienteDeEmbeddings,
    ConsultaVectorial,
    EmbeddingInvalido,
    EmbeddingNegado,
    TempoEsgotado,
    Vectores,
)

TENANT = "11111111-1111-4111-8111-111111111111"
MODELO = "modelo-falso-1024"


def vector(primeiro: float = 1.0) -> tuple[float, ...]:
    return (primeiro,) + (0.0,) * (DIMENSAO - 1)


class FakeEmbeddingProvider:
    """O fornecedor falso: conta chamadas e guarda os textos que recebeu."""

    def __init__(
        self,
        fornecedores: tuple[str, ...] = ("openai",),
        *,
        modelo: str = MODELO,
        atraso_s: float = 0.0,
        erro: Exception | None = None,
        resposta: object = None,
    ) -> None:
        self.fornecedores = fornecedores
        self.modelo = modelo
        self.atraso_s = atraso_s
        self.erro = erro
        self.resposta = resposta
        self.chamadas: list[tuple[str, tuple[str, ...], float]] = []

    def __call__(self, tenant_id: str, textos: Sequence[str], tecto_s: float) -> Vectores:
        self.chamadas.append((tenant_id, tuple(textos), tecto_s))
        if self.atraso_s:
            time.sleep(self.atraso_s)
        if self.erro is not None:
            raise self.erro
        if self.resposta is not None:
            return self.resposta  # type: ignore[return-value]
        return Vectores(self.modelo, tuple(vector() for _ in textos))


def destino(status: str = ESTADO_AUTORIZADO, *, apd: bool = True, pais: str = "US") -> dict:
    return {"especifica": False, "status": status, "tem_apd_ref": apd, "country": pais}


class Leitor:
    """O leitor de `tenant_destinations`: linhas por fornecedor, ou um erro."""

    def __init__(self, por_fornecedor: dict[str, list[dict]] | None = None) -> None:
        self.por_fornecedor = por_fornecedor or {}
        self.erro: Exception | None = None
        self.leituras: list[tuple[str, str, str]] = []

    def __call__(self, tenant: str, fornecedor: str, finalidade: str) -> list[dict]:
        self.leituras.append((tenant, fornecedor, finalidade))
        if self.erro is not None:
            raise self.erro
        return self.por_fornecedor.get(fornecedor, [])


class Relogio:
    def __init__(self) -> None:
        self.agora_ms = 0.0

    def __call__(self) -> float:
        return self.agora_ms


def nunca_sensivel(_texto: str) -> bool:
    return False


class ComRegisto(unittest.TestCase):
    def setUp(self) -> None:
        self.registo = metricas.MetricasDoIdx()
        self.relogio = Relogio()

    def consulta(
        self,
        leitor: Leitor,
        fornecedor: FakeEmbeddingProvider,
        *,
        sensivel=nunca_sensivel,
        tecto_s: float = embeddings.TECTO_DA_CONSULTA_S,
    ) -> ConsultaVectorial:
        porta = PortaSobreDestinos(leitor, relogio=self.relogio)
        cliente = ClienteDeEmbeddings(porta, fornecedor, metricas=self.registo)
        return ConsultaVectorial(cliente, sensivel, tecto_s=tecto_s, metricas=self.registo)

    def quedas(self) -> dict[str, float]:
        return {
            chave.split(":", 1)[1]: valor
            for chave, valor in self.registo.ler().items()
            if chave.startswith("embedding_fallback_total:")
        }


class TestCriterio1Gate(ComRegisto):
    """Criterio 1: sem destino autorizado, 0 chamadas e modo lexical; com ele, 1."""

    def test_sem_linha_nenhuma_zero_chamadas_e_lexical(self) -> None:
        fornecedor = FakeEmbeddingProvider()
        resultado = self.consulta(Leitor(), fornecedor).vector(TENANT, "arroz agulha", MODELO)
        self.assertEqual(len(fornecedor.chamadas), 0)
        self.assertIsNone(resultado.qvec)
        self.assertEqual(resultado.motivo, "destino_negado")
        self.assertEqual(self.quedas(), {"destino_negado": 1})

    def test_cada_estado_que_nao_autoriza_e_zero_chamadas(self) -> None:
        for linhas in (
            [destino("pendente", apd=False)],
            [destino("revogado")],
            [destino("negado")],
            [destino(ESTADO_AUTORIZADO, apd=False)],
        ):
            with self.subTest(linhas=linhas):
                fornecedor = FakeEmbeddingProvider()
                resultado = self.consulta(Leitor({"openai": linhas}), fornecedor).vector(
                    TENANT, "arroz", MODELO
                )
                self.assertEqual(fornecedor.chamadas, [])
                self.assertIsNone(resultado.qvec)

    def test_com_destino_autorizado_uma_chamada_e_o_vector(self) -> None:
        fornecedor = FakeEmbeddingProvider()
        leitor = Leitor({"openai": [destino()]})
        resultado = self.consulta(leitor, fornecedor).vector(TENANT, "Arroz Agulha!", MODELO)
        self.assertEqual(len(fornecedor.chamadas), 1)
        # O texto que sai e o do passo 1 do §5.1, como o do documento.
        self.assertEqual(fornecedor.chamadas[0][1], ("arroz agulha",))
        self.assertEqual(resultado.qvec, vector())
        self.assertIsNone(resultado.motivo)
        self.assertEqual(leitor.leituras, [(TENANT, "openai", "embeddings")])
        self.assertEqual(self.quedas(), {})

    def test_a_porta_corre_para_todos_os_fornecedores_do_alias(self) -> None:
        """O *fallback* do proxy: so o primeiro autorizado e zero chamadas."""
        fornecedor = FakeEmbeddingProvider(("anthropic", "openai"))
        leitor = Leitor({"anthropic": [destino()], "openai": [destino("pendente", apd=False)]})
        resultado = self.consulta(leitor, fornecedor).vector(TENANT, "arroz", MODELO)
        self.assertEqual(fornecedor.chamadas, [])
        self.assertEqual(resultado.motivo, "destino_negado")
        leitor.por_fornecedor["openai"] = [destino()]
        self.relogio.agora_ms += 60_000
        self.consulta(leitor, fornecedor).vector(TENANT, "arroz", MODELO)
        self.assertEqual(len(fornecedor.chamadas), 1)

    def test_erro_da_porta_e_destino_negado(self) -> None:
        """Falha fechada: a base em baixo nao deixa sair nada."""
        leitor = Leitor({"openai": [destino()]})
        leitor.erro = ConnectionError("a base caiu")
        fornecedor = FakeEmbeddingProvider()
        resultado = self.consulta(leitor, fornecedor).vector(TENANT, "arroz", MODELO)
        self.assertEqual(fornecedor.chamadas, [])
        self.assertEqual(resultado.motivo, "destino_negado")

    def test_tenant_ilegivel_e_destino_negado(self) -> None:
        fornecedor = FakeEmbeddingProvider()
        resultado = self.consulta(Leitor({"openai": [destino()]}), fornecedor).vector(
            "nao-e-uuid", "arroz", MODELO
        )
        self.assertEqual(fornecedor.chamadas, [])
        self.assertEqual(resultado.motivo, "destino_negado")

    def test_fornecedor_que_nao_diz_para_onde_envia_nao_se_autoriza(self) -> None:
        fornecedor = FakeEmbeddingProvider(())
        cliente = ClienteDeEmbeddings(
            PortaSobreDestinos(Leitor(), relogio=self.relogio), fornecedor, metricas=self.registo
        )
        with self.assertRaises(EmbeddingNegado):
            cliente.vectores(TENANT, ("arroz",), uso="consulta", tecto_s=1.0)
        self.assertEqual(fornecedor.chamadas, [])

    def test_sem_vectores_no_indice_nao_vai_ao_fornecedor_nem_conta_queda(self) -> None:
        """Sem nada com que comparar, a pergunta nao sai: e o repouso, nao uma queda."""
        fornecedor = FakeEmbeddingProvider()
        resultado = self.consulta(Leitor({"openai": [destino()]}), fornecedor).vector(
            TENANT, "arroz", None
        )
        self.assertEqual(fornecedor.chamadas, [])
        self.assertIsNone(resultado.qvec)
        self.assertIsNone(resultado.motivo)
        self.assertEqual(self.quedas(), {})


class TestCriterio2Revogacao(ComRegisto):
    """Criterio 2: revogar passa a lexical em <= 60 s, pelo TTL da porta."""

    def test_revogar_vale_no_maximo_ao_fim_do_ttl(self) -> None:
        leitor = Leitor({"openai": [destino()]})
        fornecedor = FakeEmbeddingProvider()
        consulta = self.consulta(leitor, fornecedor)
        self.assertIsNotNone(consulta.vector(TENANT, "arroz", MODELO).qvec)
        leitor.por_fornecedor["openai"] = [destino("revogado")]
        # Dentro do TTL a decisao guardada ainda vale: e o limite, e nao mais.
        self.relogio.agora_ms = 59_999
        self.assertIsNotNone(consulta.vector(TENANT, "arroz", MODELO).qvec)
        self.assertEqual(len(fornecedor.chamadas), 2)
        self.relogio.agora_ms = 60_000
        resultado = consulta.vector(TENANT, "arroz", MODELO)
        self.assertIsNone(resultado.qvec)
        self.assertEqual(resultado.motivo, "destino_negado")
        self.assertEqual(len(fornecedor.chamadas), 2)


class TestCriterio3Tecto(ComRegisto):
    """Criterio 3: 1,5 s, e ao passar degrada para lexical sem erro."""

    def test_o_tecto_da_pergunta_e_um_segundo_e_meio(self) -> None:
        self.assertEqual(embeddings.TECTO_DA_CONSULTA_S, 1.5)
        self.assertEqual(
            ConsultaVectorial(object(), nunca_sensivel).tecto_s, 1.5  # type: ignore[arg-type]
        )

    def test_passar_o_tecto_corta_a_espera_e_cai_em_lexical(self) -> None:
        fornecedor = FakeEmbeddingProvider(atraso_s=2.0)
        consulta = self.consulta(Leitor({"openai": [destino()]}), fornecedor, tecto_s=0.2)
        inicio = time.monotonic()
        resultado = consulta.vector(TENANT, "arroz", MODELO)
        decorrido = time.monotonic() - inicio
        self.assertIsNone(resultado.qvec)
        self.assertEqual(resultado.motivo, "tempo_esgotado")
        # A espera e cortada no tecto, e nao no fim da chamada lenta.
        self.assertLess(decorrido, 1.0)
        # E o fornecedor recebeu o tecto, para o seu transporte o respeitar.
        self.assertEqual(fornecedor.chamadas[0][2], 0.2)
        self.assertEqual(self.quedas(), {"tempo_esgotado": 1})

    def test_uma_resposta_depois_do_tecto_nao_conta(self) -> None:
        """Sem a espera em *thread* (o catalogo), a resposta tardia deita-se fora."""
        instantes = iter((0.0, 5.0))
        cliente = ClienteDeEmbeddings(
            PortaSobreDestinos(Leitor({"openai": [destino()]}), relogio=self.relogio),
            FakeEmbeddingProvider(),
            metricas=self.registo,
            relogio=lambda: next(instantes),
        )
        with self.assertRaises(TempoEsgotado):
            cliente.vectores(TENANT, ("arroz",), uso="catalogo", tecto_s=1.0)

    def test_uma_falha_do_fornecedor_e_lexical_sem_erro(self) -> None:
        fornecedor = FakeEmbeddingProvider(erro=RuntimeError("500 do proxy"))
        resultado = self.consulta(Leitor({"openai": [destino()]}), fornecedor).vector(
            TENANT, "arroz", MODELO
        )
        self.assertIsNone(resultado.qvec)
        self.assertEqual(resultado.motivo, "falha")

    def test_a_latencia_da_chamada_e_registada_em_ms(self) -> None:
        instantes = iter((10.0, 10.25))
        cliente = ClienteDeEmbeddings(
            PortaSobreDestinos(Leitor({"openai": [destino()]}), relogio=self.relogio),
            FakeEmbeddingProvider(),
            metricas=self.registo,
            relogio=lambda: next(instantes),
        )
        cliente.vectores(TENANT, ("arroz",), uso="consulta", tecto_s=1.5)
        self.assertEqual(self.registo.ler()["embedding_latency_ms:consulta"], 250.0)


class TestCriterio4Sensivel(ComRegisto):
    """Criterio 4: texto sensivel ou com identificador nao vai ao fornecedor."""

    def test_texto_sensivel_zero_chamadas_e_lexical(self) -> None:
        fornecedor = FakeEmbeddingProvider()
        vistos: list[str] = []

        def detector(texto_: str) -> bool:
            vistos.append(texto_)
            return True

        resultado = self.consulta(
            Leitor({"openai": [destino()]}), fornecedor, sensivel=detector
        ).vector(TENANT, "tenho diabetes, quero insulina", MODELO)
        self.assertEqual(fornecedor.chamadas, [])
        self.assertEqual(resultado.motivo, "sensivel")
        # O detector le o texto **cru**, e nao o normalizado: o `@` de um e-mail
        # e o `+` de um indicativo so existem nele.
        self.assertEqual(vistos, ["tenho diabetes, quero insulina"])
        self.assertEqual(self.quedas(), {"sensivel": 1})

    def test_um_detector_que_levanta_conta_como_sensivel(self) -> None:
        def detector(_texto: str) -> bool:
            raise RuntimeError("expressao em retrocesso")

        fornecedor = FakeEmbeddingProvider()
        resultado = self.consulta(
            Leitor({"openai": [destino()]}), fornecedor, sensivel=detector
        ).vector(TENANT, "arroz", MODELO)
        self.assertEqual(fornecedor.chamadas, [])
        self.assertEqual(resultado.motivo, "sensivel")

    def test_o_detector_corre_antes_da_porta(self) -> None:
        """Nem a base se consulta para um texto que nunca podia sair."""
        leitor = Leitor({"openai": [destino()]})
        self.consulta(leitor, FakeEmbeddingProvider(), sensivel=lambda _t: True).vector(
            TENANT, "arroz", MODELO
        )
        self.assertEqual(leitor.leituras, [])

    def test_a_metrica_nao_leva_o_texto(self) -> None:
        pergunta = "tenho hiv e moro no cazenga 923456789"
        self.consulta(Leitor(), FakeEmbeddingProvider(), sensivel=lambda _t: True).vector(
            TENANT, pergunta, MODELO
        )
        exposto = self.registo.exposicao()
        # As palavras com conteudo; «e» e «no» estao em qualquer texto de ajuda.
        for pedaco in (*(p for p in pergunta.split() if len(p) > 3), TENANT):
            with self.subTest(pedaco=pedaco):
                self.assertNotIn(pedaco, exposto)


class TestRespostaDoFornecedor(ComRegisto):
    """O fornecedor nao e de confianca: cada forma de resposta errada e lexical."""

    def cliente(self, resposta: object) -> ClienteDeEmbeddings:
        return ClienteDeEmbeddings(
            PortaSobreDestinos(Leitor({"openai": [destino()]}), relogio=self.relogio),
            FakeEmbeddingProvider(resposta=resposta),
            metricas=self.registo,
        )

    def test_cada_resposta_invalida_e_recusada(self) -> None:
        casos = {
            "dimensao": Vectores(MODELO, ((1.0, 2.0),)),
            "nan": Vectores(MODELO, ((math.nan,) + (0.0,) * (DIMENSAO - 1),)),
            "infinito": Vectores(MODELO, ((math.inf,) + (0.0,) * (DIMENSAO - 1),)),
            "booleano": Vectores(MODELO, ((True,) + (0.0,) * (DIMENSAO - 1),)),
            "a mais": Vectores(MODELO, (vector(), vector())),
            "sem modelo": Vectores(" ", (vector(),)),
            "nao e vectores": {"data": []},
        }
        for nome, resposta in casos.items():
            with self.subTest(caso=nome):
                with self.assertRaises(EmbeddingInvalido):
                    self.cliente(resposta).vectores(
                        TENANT, ("arroz",), uso="consulta", tecto_s=1.0
                    )

    def test_outro_modelo_na_resposta_e_modelo_divergente(self) -> None:
        fornecedor = FakeEmbeddingProvider(modelo="outro-modelo")
        resultado = self.consulta(Leitor({"openai": [destino()]}), fornecedor).vector(
            TENANT, "arroz", MODELO
        )
        self.assertIsNone(resultado.qvec)
        self.assertEqual(resultado.motivo, "modelo_divergente")


class TestModeloDoIndice(unittest.TestCase):
    def test_as_quatro_formas(self) -> None:
        casos = {
            "nenhum vector": ([], embeddings.ModeloDoIndice(None, False)),
            "um modelo": ([{"embedding_modelo": MODELO}], embeddings.ModeloDoIndice(MODELO, False)),
            "um modelo, tuplo": ([(MODELO,)], embeddings.ModeloDoIndice(MODELO, False)),
            "dois modelos": (
                [{"embedding_modelo": "a"}, {"embedding_modelo": "b"}],
                embeddings.ModeloDoIndice(None, True),
            ),
            "vector sem modelo": ([{"embedding_modelo": None}], embeddings.ModeloDoIndice(None, True)),
        }
        for nome, (linhas, esperado) in casos.items():
            with self.subTest(caso=nome):
                self.assertEqual(embeddings.modelo_do_indice(linhas), esperado)


class TestTextoDoCatalogo(unittest.TestCase):
    """Criterio 5, o texto: sem preco, stock, telefone nem contacto."""

    def test_o_texto_e_so_nome_marca_categoria_e_descricao(self) -> None:
        self.assertEqual(
            embeddings.texto_de_embedding("Frigorifico 250 L", "lg", None, ""),
            "Frigorifico 250 L. lg",
        )

    def test_cada_contaminacao_e_recusada(self) -> None:
        casos = {
            "Arroz 25 kg 15 000 Kz": ("dinheiro",),
            "Sapatilha, ligue 923 456 789": ("telefone",),
            "Sapatilha +244 923456789": ("telefone",),
            "Camisa 923.456.789": ("telefone",),
            "Bolo, encomendas loja.bolos@gmail.com": ("contacto",),
            "Bolo, ver www.bolos.co.ao": ("contacto",),
            "Bolo https://bolos.ao": ("contacto",),
            "Telemovel com stock": ("stock",),
        }
        for frase, motivos in casos.items():
            with self.subTest(frase=frase):
                with self.assertRaises(texto.TextoDeEmbeddingProibido) as erro:
                    embeddings.texto_de_embedding(frase)
                self.assertEqual(erro.exception.motivos, motivos)
                self.assertNotIn(frase, str(erro.exception))

    def test_o_preco_com_muitos_algarismos_e_dinheiro_e_nao_telefone(self) -> None:
        self.assertEqual(texto.motivos_de_recusa("Carro 2.500.000.000 kz"), ("dinheiro",))

    def test_o_que_nao_e_contacto_passa(self) -> None:
        for frase in (
            "Telefone fixo Panasonic KX-TS500",
            "Telemovel Samsung Galaxy A54 128GB",
            "Televisor 55 polegadas 4K 2024",
            "Arroz 25 kg",
            "Pack 12 x 330 ml",
        ):
            with self.subTest(frase=frase):
                self.assertEqual(texto.exigir_texto_de_embedding(frase), frase)


class BdFalsa:
    """O `ClienteSql` do KAM-006: responde por SQL e regista as instrucoes."""

    def __init__(self, documentos: list[dict], outro_modelo: bool = False) -> None:
        self.documentos = documentos
        self.outro_modelo = outro_modelo
        self.instrucoes: list[tuple[str, tuple]] = []

    def executar(self, sql: str, parametros: Sequence[object] = ()) -> Resultado:
        self.instrucoes.append((sql, tuple(parametros)))
        if sql == embeddings.SQL_POR_EMBEBER:
            return Resultado(linhas=tuple(self.documentos), contagem=len(self.documentos))
        if sql == embeddings.SQL_OUTRO_MODELO:
            linhas = ({"existe": 1},) if self.outro_modelo else ()
            return Resultado(linhas=linhas, contagem=len(linhas))
        if sql.lstrip().startswith("UPDATE idx.search_doc d"):
            return Resultado(linhas=(), contagem=(len(parametros) - 2) // 6)
        raise AssertionError(f"instrucao inesperada: {sql[:60]}")

    def gravacoes(self) -> list[tuple]:
        return [p for s, p in self.instrucoes if s.lstrip().startswith("UPDATE")]


def documento(doc_id: str, nome: str) -> dict:
    return {
        "doc_id": doc_id,
        "nome": nome,
        "nome_norm": texto.normalizar(nome),
        "marca_canon": None,
        "categoria_canon": None,
        "descr_norm": "",
    }


class TestWorkerDoCatalogo(ComRegisto):
    """Uma volta do *worker*: porta, *lint*, um modelo por coluna, cursor."""

    def cliente(self, leitor: Leitor, fornecedor: FakeEmbeddingProvider) -> ClienteDeEmbeddings:
        return ClienteDeEmbeddings(
            PortaSobreDestinos(leitor, relogio=self.relogio), fornecedor, metricas=self.registo
        )

    def test_grava_os_que_passam_o_lint_e_conta_os_recusados(self) -> None:
        bd = BdFalsa([
            documento("00000000-0000-4000-8000-000000000001", "Arroz Agulha 25 kg"),
            documento("00000000-0000-4000-8000-000000000002", "Bolo, ligue 923 456 789"),
            documento("00000000-0000-4000-8000-000000000003", "Feijao 15 000 Kz"),
        ])
        fornecedor = FakeEmbeddingProvider()
        volta = embeddings.embeber_catalogo(
            bd, TENANT, self.cliente(Leitor({"openai": [destino()]}), fornecedor), MODELO
        )
        self.assertEqual(
            volta,
            embeddings.VoltaDoCatalogo(3, 1, 2, "00000000-0000-4000-8000-000000000003"),
        )
        # So o texto limpo saiu, e numa chamada.
        self.assertEqual(len(fornecedor.chamadas), 1)
        self.assertEqual(fornecedor.chamadas[0][1], ("Arroz Agulha 25 kg",))
        (gravacao,) = bd.gravacoes()
        self.assertEqual(gravacao[0], MODELO)
        self.assertEqual(gravacao[-1], MODELO)
        self.assertEqual(gravacao[1], "00000000-0000-4000-8000-000000000001")
        self.assertEqual(gravacao[2], embeddings.em_texto(vector()))
        self.assertIn("embedding_latency_ms:catalogo", self.registo.ler())

    def test_sem_destino_nada_sai_e_nada_se_grava(self) -> None:
        bd = BdFalsa([documento("00000000-0000-4000-8000-000000000001", "Arroz")])
        fornecedor = FakeEmbeddingProvider()
        volta = embeddings.embeber_catalogo(
            bd, TENANT, self.cliente(Leitor(), fornecedor), MODELO
        )
        self.assertEqual(volta.motivo, "destino_negado")
        self.assertEqual(volta.gravados, 0)
        self.assertEqual(fornecedor.chamadas, [])
        self.assertEqual(bd.gravacoes(), [])

    def test_outro_modelo_no_tenant_nao_chama_o_fornecedor(self) -> None:
        """Criterio 6, a metade sem DDL: nunca dois modelos na coluna do tenant."""
        bd = BdFalsa([documento("00000000-0000-4000-8000-000000000001", "Arroz")], outro_modelo=True)
        fornecedor = FakeEmbeddingProvider()
        volta = embeddings.embeber_catalogo(
            bd, TENANT, self.cliente(Leitor({"openai": [destino()]}), fornecedor), MODELO
        )
        self.assertEqual(volta.motivo, "modelo_divergente")
        self.assertEqual(fornecedor.chamadas, [])
        self.assertEqual(bd.gravacoes(), [])

    def test_o_fornecedor_responder_com_outro_modelo_nao_grava(self) -> None:
        bd = BdFalsa([documento("00000000-0000-4000-8000-000000000001", "Arroz")])
        volta = embeddings.embeber_catalogo(
            bd,
            TENANT,
            self.cliente(Leitor({"openai": [destino()]}), FakeEmbeddingProvider(modelo="b")),
            MODELO,
        )
        self.assertEqual(volta.motivo, "modelo_divergente")
        self.assertEqual(bd.gravacoes(), [])

    def test_uma_falha_nao_levanta_e_o_lote_repete(self) -> None:
        bd = BdFalsa([documento("00000000-0000-4000-8000-000000000001", "Arroz")])
        fornecedor = FakeEmbeddingProvider(erro=RuntimeError("503"))
        volta = embeddings.embeber_catalogo(
            bd, TENANT, self.cliente(Leitor({"openai": [destino()]}), fornecedor), MODELO
        )
        self.assertEqual((volta.motivo, volta.gravados), ("falha", 0))

    def test_o_cursor_e_o_lote_vao_ao_sql(self) -> None:
        bd = BdFalsa([])
        volta = embeddings.embeber_catalogo(
            bd, TENANT, self.cliente(Leitor(), FakeEmbeddingProvider()), MODELO,
            depois_de="00000000-0000-4000-8000-000000000009", lote=10,
        )
        self.assertEqual(volta, embeddings.VoltaDoCatalogo(0, 0, 0, None))
        self.assertEqual(
            bd.instrucoes,
            [(embeddings.SQL_POR_EMBEBER,
              ("00000000-0000-4000-8000-000000000009",) * 2 + (10,))],
        )

    def test_a_escrita_confere_o_texto_e_o_modelo(self) -> None:
        sql = embeddings.sql_gravar_embeddings(2)
        for clausula in (
            "d.nome_norm = u.nome_norm",
            "d.marca_canon IS NOT DISTINCT FROM u.marca_canon",
            "d.categoria_canon IS NOT DISTINCT FROM u.categoria_canon",
            "d.descr_norm = u.descr_norm",
            "d.embedding IS NULL",
            "o.embedding_modelo IS DISTINCT FROM %s",
        ):
            with self.subTest(clausula=clausula):
                self.assertIn(clausula, sql)
        self.assertEqual(sql.count("%s"), 2 + 2 * 6)


class TestReembedding(unittest.TestCase):
    """Criterio 5, o disparo: o consumidor anula o vector so quando o texto muda."""

    TEXTO = ("nome_norm", "marca_canon", "categoria_canon", "descr_norm")

    def test_cada_coluna_do_texto_escrita_e_comparada(self) -> None:
        sql = consumidor.SQL_ESCREVER_DOCUMENTO
        colunas = re.search(r"INSERT INTO idx\.search_doc\s*\(([^)]*)\)", sql)
        assert colunas is not None
        escritas = {c.strip() for c in colunas.group(1).split(",")}
        self.assertEqual(
            set(consumidor.COLUNAS_DO_TEXTO_ESCRITAS), escritas & set(self.TEXTO)
        )
        for coluna in consumidor.COLUNAS_DO_TEXTO_ESCRITAS:
            with self.subTest(coluna=coluna):
                self.assertIn(f"idx.search_doc.{coluna}", sql)
                self.assertIn(f"EXCLUDED.{coluna}", sql)

    def test_o_vector_e_o_modelo_caem_juntos(self) -> None:
        sql = consumidor.SQL_ESCREVER_DOCUMENTO
        self.assertIn("THEN idx.search_doc.embedding END", sql)
        self.assertIn("THEN idx.search_doc.embedding_modelo END", sql)
        self.assertNotIn("{texto_igual}", sql)

    def test_o_preco_nao_esta_na_instrucao(self) -> None:
        self.assertNotRegex(consumidor.SQL_ESCREVER_DOCUMENTO, r"preco|stock")


class TestArranqueDoExecutor(unittest.TestCase):
    def test_as_threads_sao_partilhadas(self) -> None:
        self.assertIs(embeddings._executor(), embeddings._executor())
        self.assertLessEqual(embeddings._executor()._max_workers, 8)

    def test_chamadas_concorrentes_respeitam_cada_uma_o_seu_tecto(self) -> None:
        leitor = Leitor({"openai": [destino()]})
        registo = metricas.MetricasDoIdx()
        consulta = ConsultaVectorial(
            ClienteDeEmbeddings(
                PortaSobreDestinos(leitor), FakeEmbeddingProvider(atraso_s=0.05),
                metricas=registo,
            ),
            nunca_sensivel,
            metricas=registo,
        )
        resultados: list[object] = []
        fios = [
            threading.Thread(
                target=lambda: resultados.append(consulta.vector(TENANT, "arroz", MODELO).qvec)
            )
            for _ in range(4)
        ]
        for fio in fios:
            fio.start()
        for fio in fios:
            fio.join()
        self.assertEqual(resultados, [vector()] * 4)


if __name__ == "__main__":
    unittest.main()
