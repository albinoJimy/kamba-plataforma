"""O fornecedor de embeddings do AGR e o modo hibrido do executor (KAM-063).

O `ClienteDeLlm.embeber` corre com o duplo de transporte e de ligacao do
`test_llm_cliente.py` — o mesmo que prova o `chamar` —, para que a porta, a
chave virtual e a linha de `dat.llm_call_log` se meçam pelo mesmo instrumento.
"""

from __future__ import annotations

import unittest
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest import mock

from kamba_core.idx import metricas as idx_metricas
from kamba_core.idx.embeddings import (
    DIMENSAO,
    ClienteDeEmbeddings,
    ConsultaVectorial,
    EmbeddingNegado,
)
from kamba_core.idx.pesquisa import MODO_HIBRIDO, Procura

from kamba_agr.llm import aliases as aliases_mod
from kamba_agr.llm import destinos as destinos_mod
from kamba_agr.llm import precos as precos_mod
from kamba_agr.llm.cliente import ClienteDeLlm, ContextoDeChamada
from kamba_agr.llm.erros import (
    RESULTADO_DESTINO,
    RESULTADO_ERRO,
    RESULTADO_OK,
    DestinoNegado,
    FornecedorFalhou,
)
from kamba_agr.privacidade import minimizacao
from kamba_agr.tls import embeddings as tls_embeddings
from kamba_agr.tls import idx

from test_idx import _pedido, _procura
from test_llm_cliente import TENANT, _Ligacao, _Transporte

ALIAS_EMBED = aliases_mod.Alias(
    nome="kamba-embed",
    papel="embed",
    timeout=20,
    fornecedores=("openai",),
    modelos=("emb-ensaio-1024",),
)
PRECOS = {
    ("openai", "emb-ensaio-1024"): precos_mod.Preco(
        "openai", "emb-ensaio-1024",
        Decimal("0.02"), Decimal("0.0"), Decimal("0.0"), "CONFIRMADO", "ensaio",
    ),
}
CTX = ContextoDeChamada(tenant_id=TENANT, trace_id="0af7651916cd43dd8448eb211c80319c")
_MIN = minimizacao.ContextoDeMinimizacao(tenant_id=TENANT, thread_id="ensaio")


def _textos(*textos: str) -> list[minimizacao.MinimisedText]:
    return [minimizacao.minimise(t, _MIN)[0] for t in textos]


def _corpo(quantos: int = 1, *, ordem: list[int] | None = None, dimensao: int = DIMENSAO) -> dict:
    indices = ordem if ordem is not None else list(range(quantos))
    return {
        "model": "openai/emb-ensaio-1024",
        "data": [
            {"index": i, "embedding": [float(i + 1)] + [0.0] * (dimensao - 1)}
            for i in indices
        ],
        "usage": {"prompt_tokens": 120_000, "total_tokens": 120_000},
    }


def _cliente(
    transporte: _Transporte, ambiente: str = destinos_mod.AMBIENTE_STAGING
) -> tuple[ClienteDeLlm, _Ligacao]:
    ligacao = _Ligacao()
    cliente = ClienteDeLlm(
        aliases={"embed": ALIAS_EMBED},
        tabela_de_precos=PRECOS,
        porta_de_destinos=destinos_mod.arrancar(ambiente),
        abrir_ligacao=lambda: ligacao,
        chave_virtual=lambda t: f"sk-virtual-{t}",
        url_do_proxy="http://litellm:4000",
        transporte=transporte,
    )
    return cliente, ligacao


class TestEmbeberDoGateway(unittest.TestCase):
    """O `/embeddings` do proxy: chave virtual, porta, uma linha com o custo."""

    def test_o_pedido_e_o_do_esquema_e_vai_com_a_chave_do_tenant(self) -> None:
        transporte = _Transporte((200, _corpo(2, ordem=[1, 0]), {}))
        cliente, ligacao = _cliente(transporte)
        resposta = cliente.embeber("embed", _textos("arroz", "feijao"), CTX, 1.5)
        ((url, cabecalhos, corpo, tecto),) = transporte.chamadas
        self.assertEqual(url, "http://litellm:4000/embeddings")
        self.assertEqual(cabecalhos["Authorization"], f"Bearer sk-virtual-{TENANT}")
        self.assertEqual(corpo, {"model": "kamba-embed", "input": ["arroz", "feijao"]})
        self.assertEqual(tecto, 1.5)
        # Pelo `index`, e nao pela ordem da lista.
        self.assertEqual([v[0] for v in resposta.vectores], [1.0, 2.0])
        self.assertEqual(resposta.modelo, "emb-ensaio-1024")
        (linha,) = ligacao.linhas()
        self.assertEqual(linha["papel"], "embed")
        self.assertEqual(linha["resultado"], RESULTADO_OK)
        self.assertEqual(linha["tokens_in"], 120_000)
        self.assertEqual(linha["fornecedor"], "openai")
        # O custo por tenant do criterio 7: 120 mil tokens a 0,02 USD por milhao.
        self.assertEqual(linha["custo_usd"], Decimal("0.0024"))

    def test_sem_tecto_e_o_do_alias(self) -> None:
        transporte = _Transporte((200, _corpo(), {}))
        cliente, _ = _cliente(transporte)
        cliente.embeber("embed", _textos("arroz"), CTX)
        self.assertGreater(transporte.chamadas[0][3], 20)

    def test_destino_negado_zero_chamadas_e_uma_linha(self) -> None:
        transporte = _Transporte()
        cliente, ligacao = _cliente(transporte, destinos_mod.AMBIENTE_PROD)
        with self.assertRaises(DestinoNegado):
            cliente.embeber("embed", _textos("arroz"), CTX, 1.5)
        self.assertEqual(transporte.chamadas, [])
        (linha,) = ligacao.linhas()
        self.assertEqual(linha["resultado"], RESULTADO_DESTINO)

    def test_texto_cru_nao_passa(self) -> None:
        transporte = _Transporte()
        cliente, _ = _cliente(transporte)
        with self.assertRaises(minimizacao.TextoNaoMinimizado):
            cliente.embeber("embed", ["arroz"], CTX)  # type: ignore[list-item]
        self.assertEqual(transporte.chamadas, [])

    def test_resposta_sem_os_vectores_todos_e_falha_com_linha(self) -> None:
        for corpo in (
            _corpo(1),  # pediram-se dois
            {**_corpo(2), "data": [{"index": 0, "embedding": [1.0]}, {"index": 0, "embedding": [1.0]}]},
            {**_corpo(2), "data": [{"index": 0, "embedding": "x"}, {"index": 1, "embedding": [1.0]}]},
            {"error": "nada"},
        ):
            with self.subTest(corpo=str(corpo)[:60]):
                cliente, ligacao = _cliente(_Transporte((200, corpo, {})))
                with self.assertRaises(FornecedorFalhou):
                    cliente.embeber("embed", _textos("arroz", "feijao"), CTX, 1.5)
                (linha,) = ligacao.linhas()
                self.assertEqual(linha["resultado"], RESULTADO_ERRO)

    def test_fornecedores_e_modelo_do_papel(self) -> None:
        cliente, _ = _cliente(_Transporte())
        self.assertEqual(cliente.fornecedores_de("embed"), ("openai",))
        self.assertEqual(cliente.modelo_de("embed"), "emb-ensaio-1024")
        self.assertEqual(cliente.fornecedores_de("chat"), ())
        self.assertIsNone(cliente.modelo_de("chat"))


class TestFornecedorDoGateway(unittest.TestCase):
    """O adaptador: nenhum identificador sai, nem mascarado."""

    def test_identificador_directo_nao_sai(self) -> None:
        transporte = _Transporte()
        cliente, _ = _cliente(transporte)
        fornecedor = tls_embeddings.FornecedorDoGateway(cliente)
        for texto in ("bolo, ligue 923 456 789", "escreva a joao@exemplo.co.ao"):
            with self.subTest(texto=texto):
                with self.assertRaises(tls_embeddings.IdentificadorNoTexto) as erro:
                    fornecedor(TENANT, [texto], 1.5)
                self.assertNotIn("923", str(erro.exception))
        self.assertEqual(transporte.chamadas, [])

    def test_aceita_texto_a_texto(self) -> None:
        """O *worker* pergunta antes de juntar: um recusado nao derruba o lote."""
        transporte = _Transporte()
        cliente, _ = _cliente(transporte)
        fornecedor = tls_embeddings.FornecedorDoGateway(cliente)
        self.assertTrue(fornecedor.aceita("arroz agulha 25 kg"))
        self.assertFalse(fornecedor.aceita("bolo, ligue 923 456 789"))
        self.assertEqual(transporte.chamadas, [])

    def test_os_fornecedores_sao_os_do_alias(self) -> None:
        cliente, _ = _cliente(_Transporte())
        self.assertEqual(tls_embeddings.FornecedorDoGateway(cliente).fornecedores, ("openai",))

    def test_a_porta_do_nucleo_nega_antes_do_gateway(self) -> None:
        """A cadeia de producao: `prod` sem destino, zero pedidos ao proxy."""
        transporte = _Transporte()
        cliente, ligacao = _cliente(transporte, destinos_mod.AMBIENTE_PROD)
        nucleo = ClienteDeEmbeddings(
            destinos_mod.arrancar(destinos_mod.AMBIENTE_PROD),
            tls_embeddings.FornecedorDoGateway(cliente),
            metricas=idx_metricas.MetricasDoIdx(),
        )
        with self.assertRaises(EmbeddingNegado):
            nucleo.vectores(TENANT, ["arroz"], uso="consulta", tecto_s=1.5)
        self.assertEqual(transporte.chamadas, [])
        # A porta do nucleo negou primeiro, e o gateway nem foi chamado.
        self.assertEqual(ligacao.linhas(), [])

    def test_com_destino_um_pedido_e_o_vector(self) -> None:
        transporte = _Transporte((200, _corpo(), {}))
        cliente, _ = _cliente(transporte)
        nucleo = ClienteDeEmbeddings(
            destinos_mod.arrancar(destinos_mod.AMBIENTE_STAGING),
            tls_embeddings.FornecedorDoGateway(cliente),
            metricas=idx_metricas.MetricasDoIdx(),
        )
        vectores = nucleo.vectores(TENANT, ["arroz"], uso="consulta", tecto_s=1.5)
        self.assertEqual(len(transporte.chamadas), 1)
        self.assertEqual(vectores.modelo, "emb-ensaio-1024")
        self.assertEqual(len(vectores.vectores[0]), DIMENSAO)


class TestSensivel(unittest.TestCase):
    """Criterio 4: o detector que o AGR passa ao nucleo."""

    def test_o_que_nao_vai(self) -> None:
        for texto in (
            "tenho diabetes, preciso de insulina",
            "o meu cartao e 4111 1111 1111 1111",
            "liga para 923 456 789",
            "manda para joao@exemplo.co.ao",
        ):
            with self.subTest(texto=texto):
                self.assertTrue(tls_embeddings.sensivel(texto))

    def test_o_que_vai(self) -> None:
        for texto in ("quero arroz agulha", "sapatilhas nike 42", "frigorifico lg"):
            with self.subTest(texto=texto):
                self.assertFalse(tls_embeddings.sensivel(texto))


class TestConsultaVectorial(unittest.TestCase):
    def test_sem_modelo_escolhido_nao_ha_consulta(self) -> None:
        cliente, _ = _cliente(_Transporte())
        por_decidir = ClienteDeLlm(
            aliases={"embed": aliases_mod.Alias(
                nome="kamba-embed", papel="embed", timeout=20,
                fornecedores=("openai",), modelos=("por_decidir",),
            )},
            tabela_de_precos={},
            porta_de_destinos=destinos_mod.arrancar(destinos_mod.AMBIENTE_STAGING),
            abrir_ligacao=lambda: _Ligacao(),
            chave_virtual=lambda t: t,
            transporte=_Transporte(),
        )
        porta = destinos_mod.arrancar(destinos_mod.AMBIENTE_STAGING)
        self.assertIsNone(tls_embeddings.consulta_vectorial(por_decidir, porta))
        self.assertIsInstance(tls_embeddings.consulta_vectorial(cliente, porta), ConsultaVectorial)

    def test_o_alias_do_repositorio_ainda_nao_tem_modelo(self) -> None:
        """Hoje: `kamba-embed` em `por_decidir`, logo a pesquisa e lexical."""
        import pathlib

        reais = aliases_mod.ler(pathlib.Path(__file__).resolve().parents[3] / "llm")
        self.assertEqual(reais["embed"].modelos[0], tls_embeddings.MODELO_POR_DECIDIR)


class TestExecutorHibrido(unittest.TestCase):
    """O modo que correu decide o pontuador e a etiqueta `modo` (KAM-193)."""

    def setUp(self) -> None:
        self.registo = idx_metricas.METRICAS
        self.registo.repor()
        self.addCleanup(self.registo.repor)
        self.vectorial = ConsultaVectorial(
            mock.Mock(spec=ClienteDeEmbeddings), lambda _t: False
        )

    def test_hibrido_escreve_o_modo_e_normaliza_pelos_tres_ramos(self) -> None:
        linha = {"sku": "a", "product_ref": "a", "nome": "A", "preco_tipo": "fixo"}
        procura = _procura(((linha, 0.5 / 61),))
        hibrida = Procura(procura.normalizacao, procura.linhas, MODO_HIBRIDO)
        ligacao = idx.LigacaoVectorial()
        ligacao.ligar(self.vectorial)
        with mock.patch.object(idx.pesquisa, "procurar", return_value=hibrida) as procurar:
            resposta = idx.executar(_pedido("arroz"), ligacao)
        self.assertEqual(resposta.data["candidatos"][0]["score"], 0.5)
        self.assertEqual(self.registo.ler()["idx_mode:hibrido"], 1)
        self.assertNotIn("idx_mode:lexical", self.registo.ler())
        # A consulta vai inteira, e o tecto da tool tambem: quem corta o prazo
        # do vector e o `procurar`, que conta a porta e a primeira transaccao.
        self.assertIs(procurar.call_args.kwargs["vectorial"], self.vectorial)
        self.assertEqual(procurar.call_args.kwargs["tecto_ms"], 2_000)

    def test_ligacao_por_ligar_e_lexical(self) -> None:
        with mock.patch.object(idx.pesquisa, "procurar", return_value=_procura()) as procurar:
            idx.executar(_pedido("arroz"), idx.LigacaoVectorial())
        self.assertIsNone(procurar.call_args.kwargs["vectorial"])
        self.assertEqual(self.registo.ler()["idx_mode:lexical"], 1)

    def test_os_executores_levam_a_ligacao(self) -> None:
        ligacao = idx.LigacaoVectorial()
        executor = idx.executores_do_idx(ligacao)["search_catalog"]
        self.assertIs(executor.keywords["ligacao"], ligacao)


if __name__ == "__main__":
    unittest.main()
