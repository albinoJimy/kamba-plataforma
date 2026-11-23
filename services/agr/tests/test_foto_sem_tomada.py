"""A foto do dono sem prender a tomada da TLS (KAM-244, achados 4 e 5 do KAM-231).

Tres propriedades, pela ToolLayer real e pelo grafo do dono:

1. **Quatro fotos lentas nao atrasam uma leitura de outro tenant** na mesma
   replica: a visao e o screening correm sem a tomada (`Pedido.sem_tomada`, como
   o `submit_quote` do KAM-230). Canario: sem largar, a leitura espera pela
   visao.
2. **As escritas do fim vao pela ligacao retomada**, e nao pela largada, que ja
   pode estar noutra invocacao (`TomadaDaInvocacao`).
3. **Adversarial: a visao e o screening nos seus tectos ao mesmo tempo** acabam
   dentro do tecto da tool, sem `UPSTREAM_TIMEOUT`, e a ingestao fica num
   estado que o turno seguinte retoma ate ao resumo («Tentar outra vez»).

Com tempo de parede, mas curto: o tecto da tool e as reservas do pipeline
descem a escala no ensaio adversarial; a soma no pior caso, a 25 s, mede-se no
`libs/py-core/tests/test_catalogo_prazo.py` com um relogio falso.
"""

from __future__ import annotations

import asyncio
import threading
import time
import unittest
import uuid
from typing import Any
from unittest import mock

from test_catalogo_dono import A, AGORA, B, CONTACTO_A, Mundo, _ate_ao_rascunho, jpeg  # noqa: F401
from test_dono import _LigacaoDosModulos

from kamba_agr.catalogo import regras
from kamba_agr.catalogo.montagem import TomadaDaInvocacao
from kamba_agr.tls import camada as camada_mod
from kamba_agr.tls import catalogo_tools
from kamba_agr.tls.camada import ToolLayer
from kamba_agr.tls.catalogo import catalogo_do_piloto
from kamba_agr.tls.erros import UPSTREAM_TIMEOUT, ErroDeTool, ToolResult
from kamba_agr.tls.especificacoes import Catalogo, Pedido
from kamba_agr.verticais.dono import catalogo as conversa
from kamba_agr.verticais.dono import nos as nos_do_dono
from kamba_core.catalogo import estados
from kamba_core.catalogo import pipeline as pipeline_mod
from kamba_core.catalogo.pipeline import REGRAS_RETOMAVEIS, ErroDaVisao

#: Quanto a visao lenta demora no ensaio de concorrencia, em segundos.
VISAO_LENTA_S = 2.0

_TRINCO = threading.Lock()


def _lenta(funcao: Any, demora_s: float, erro: type[Exception], dentro: list[int] | None = None) -> Any:
    """Uma porta que espera `demora_s` de parede, cortada ao `tecto_s` que recebeu.

    `dentro` conta quantas chamadas ja comecaram a esperar.
    """

    def porta(*args: Any, tecto_s: float | None = None, **kwargs: Any) -> Any:
        if dentro is not None:
            with _TRINCO:
                dentro[0] += 1
        espera = demora_s if tecto_s is None else max(0.0, min(demora_s, tecto_s))
        time.sleep(espera)
        if tecto_s is not None and demora_s > tecto_s:
            raise erro("passou do tecto")
        return funcao(*args, tecto_s=tecto_s, **kwargs)

    return porta


def _camada(m: Mundo, **kw: Any) -> ToolLayer:
    """A ToolLayer do `Mundo` com **quatro** tomadas distintas, uma por vaga."""
    executores = catalogo_tools.executores(m.portas, lambda: AGORA)
    do_catalogo = catalogo_do_piloto(executores)
    especificacoes = tuple(do_catalogo[n] for n in ("create_product_draft", "get_catalog_status"))
    return ToolLayer(
        Catalogo(especificacoes),
        abrir_ligacao=lambda: _LigacaoDosModulos({"vendedor", "catalogo"}),
        ligacoes=4,
        **kw,
    )


async def _invocar(camada: ToolLayer, m: Mundo, tenant: str, nome: str, args: dict[str, Any]) -> ToolResult:
    return await camada.invoke(m.ctx(tenant), nome, args, allowed=nos_do_dono.TOOLS_DO_DONO)


# ====================================================================== 1


class TestQuatroFotosNaoParamAReplica(unittest.TestCase):
    def setUp(self) -> None:
        self.m = Mundo({f"m{n}": jpeg(f"P{n}".encode()) for n in range(4)})
        self.addCleanup(self.m.fechar)
        self.dentro = [0]
        self.m.visao.extrair = _lenta(  # type: ignore[method-assign]
            self.m.visao.extrair, VISAO_LENTA_S, ErroDaVisao, self.dentro
        )

    def _leitura_durante_quatro_fotos(self) -> tuple[float, list[ToolResult]]:
        async def correr() -> tuple[float, list[ToolResult]]:
            camada = _camada(self.m)
            fotos = [
                asyncio.create_task(_invocar(camada, self.m, A, "create_product_draft", {"media_id": f"m{n}"}))
                for n in range(4)
            ]
            # **As quatro dentro da visao**, sem tomada (ou com ela, no canario).
            # Esperar um tempo fixo media outra coisa: a analise da imagem, antes
            # da visao, e CPU com o GIL, e atrasava a leitura por ela.
            limite = time.monotonic() + 60
            while self.dentro[0] < 4:
                self.assertLess(time.monotonic(), limite, "as fotos nao chegaram a visao")
                await asyncio.sleep(0.01)
            inicio = time.monotonic()
            leitura = await _invocar(camada, self.m, B, "get_catalog_status", {})
            demorou = time.monotonic() - inicio
            self.assertTrue(leitura.ok, leitura.error)
            return demorou, list(await asyncio.gather(*fotos))

        return asyncio.run(correr())

    def test_a_leitura_de_outro_tenant_nao_espera_pela_visao(self) -> None:
        demorou, fotos = self._leitura_durante_quatro_fotos()
        self.assertLess(demorou, 0.5)
        self.assertTrue(all(f.ok for f in fotos), [f.error for f in fotos])
        self.assertEqual({f.data["estado"] for f in fotos}, {estados.A_PERGUNTAR})
        self.assertEqual(len(self.m.repo.todas()), 4)

    def test_canario_sem_largar_a_tomada_a_leitura_espera(self) -> None:
        """Com o pipeline a correr a visao **com** a tomada, a leitura espera por ela."""
        with mock.patch.object(TomadaDaInvocacao, "fora_da_ligacao", lambda self, trabalho: trabalho()):
            demorou, fotos = self._leitura_durante_quatro_fotos()
        self.assertGreater(demorou, VISAO_LENTA_S / 2)
        self.assertTrue(all(f.ok for f in fotos))


# ====================================================================== 2


class _Ligacao:
    """Uma ligacao com nome, para saber qual foi usada."""

    def __init__(self, nome: str) -> None:
        self.nome = nome

    def close(self) -> None:
        return None


class TestALigacaoCorrente(unittest.TestCase):
    def test_a_tomada_troca_a_ligacao_e_delega_na_de_agora(self) -> None:
        largada, retomada = _Ligacao("largada"), _Ligacao("retomada")
        tomada = TomadaDaInvocacao(largada, lambda trabalho: (trabalho(), retomada))
        self.assertEqual(tomada.nome, "largada")
        self.assertEqual(tomada.fora_da_ligacao(lambda: 7), 7)
        self.assertIs(tomada.ligacao, retomada)
        self.assertEqual(tomada.nome, "retomada")
        tomada.close()  # nao fecha nada: a ligacao e da fila da ToolLayer

    def test_sem_largar_o_trabalho_corre_com_a_ligacao(self) -> None:
        ligacao = _Ligacao("unica")
        tomada = TomadaDaInvocacao(ligacao)
        self.assertEqual(tomada.fora_da_ligacao(lambda: "ok"), "ok")
        self.assertIs(tomada.ligacao, ligacao)

    def test_o_botao_de_publicar_e_proposto_na_ligacao_retomada(self) -> None:
        """Uma correccao que volta ao screening: o `propor` vai pela retomada."""
        m = Mundo()
        self.addCleanup(m.fechar)
        r = m.invocar("create_product_draft", {"media_id": "m1"})
        _ate_ao_rascunho(m, r.data["ingestao"])
        usadas: list[Any] = []
        propor = catalogo_tools.accoes.propor

        def registar(ligacao: Any, *args: Any) -> str:
            usadas.append(ligacao)
            return propor(ligacao, *args)

        largada, retomada = _Ligacao("largada"), _Ligacao("retomada")
        pedido = Pedido(
            ctx=m.ctx(),
            args=catalogo_tools.ArgumentosDeCreateProductDraft(
                ingestao=r.data["ingestao"], respostas={"material": "algodao"}
            ),
            timeout_ms=25_000,
            ligacao=largada,
            largar_tomada=lambda trabalho: (trabalho(), retomada),
        )
        executor = catalogo_tools.executores(m.portas, lambda: AGORA)["create_product_draft"]
        with mock.patch.object(catalogo_tools.accoes, "propor", registar):
            resposta = executor(pedido)
        self.assertEqual(resposta.data["estado"], estados.RASCUNHO)
        self.assertTrue(usadas)
        self.assertTrue(all(lig is retomada for lig in usadas), [getattr(l, "nome", l) for l in usadas])


# ====================================================================== 3


class TestAdversarialOsDoisNoTecto(unittest.TestCase):
    """A visao e o screening a demorar o tecto deles, ao mesmo tempo, pela ToolLayer.

    A escala desce dez vezes: a tool tem 2,5 s e as reservas do pipeline um
    decimo das de producao. A visao e o screening «demoram» o tecto de producao
    deles (18 s e 20 s), cortados no que recebem.
    """

    def setUp(self) -> None:
        self.m = Mundo()
        self.addCleanup(self.m.fechar)
        remendos = [
            mock.patch.dict(camada_mod.TECTOS_POR_TOOL, {"create_product_draft": 2_500}),
            mock.patch.object(pipeline_mod, "RESERVA_DAS_ESCRITAS_MS", 100),
            mock.patch.object(pipeline_mod, "RESERVA_DEPOIS_DO_SCREENING_MS", 300),
            mock.patch.object(pipeline_mod, "RESERVA_DEPOIS_DA_VISAO_MS", 900),
        ]
        for remendo in remendos:
            remendo.start()
            self.addCleanup(remendo.stop)
        self.m.visao.extrair = _lenta(self.m.visao.extrair, 18.0, ErroDaVisao)  # type: ignore[method-assign]
        self.screen_rapido = self.m.screening.screen
        self.m.screening.screen = _lenta(self.screen_rapido, 20.0, RuntimeError)  # type: ignore[method-assign]

    def test_acaba_dentro_do_tecto_e_retoma_com_o_toque_seguinte(self) -> None:
        inicio = time.monotonic()
        r = self.m.invocar("create_product_draft", {"media_id": "m1"})
        demorou = time.monotonic() - inicio
        self.assertTrue(r.ok, r.error)
        self.assertLess(demorou, 2.5)
        self.assertEqual(r.data["estado"], estados.BLOQUEADA_CATEGORIA)
        self.assertTrue(r.data["retomavel"])
        (linha,) = self.m.repo.todas()
        self.assertIn(linha.categoria_restrita, REGRAS_RETOMAVEIS)
        # O turno seguinte: o toque «Tentar outra vez», com o screening a responder.
        self.m.screening.screen = self.screen_rapido  # type: ignore[method-assign]
        _final, texto, botoes = self.m.turno(botao=regras.botao_de_retomar(linha.id))
        self.assertEqual(self.m.repo.ler(A, linha.id).estado, estados.A_PERGUNTAR)  # type: ignore[union-attr]
        self.assertIn(regras.referencia_do_produto(linha.id), texto)
        del botoes


# ====================================================================== os adaptadores


class _Com:
    """O `ClienteDoCom`: guarda o tecto e o corpo de cada chamada."""

    def __init__(self, resposta: dict[str, Any] | None = None) -> None:
        self.chamadas: list[tuple[str, dict[str, Any], int]] = []
        self.resposta = resposta or {}

    def chamar(self, rota: str, _ctx: Any, corpo: dict[str, Any], timeout_ms: int) -> dict[str, Any]:
        self.chamadas.append((rota, corpo, timeout_ms))
        return self.resposta


class _Llm:
    def __init__(self) -> None:
        self.tectos: list[float | None] = []

    def fornecedores_de(self, _papel: str) -> tuple[str, ...]:
        return ("anthropic",)

    def ver(self, _imagem: Any, _ctx: Any, *, tecto_s: float | None = None) -> Any:
        self.tectos.append(tecto_s)
        return mock.Mock(texto="{}", custo_usd=None)


class TestOsAdaptadoresCumpremOTecto(unittest.TestCase):
    """O menor dos dois tectos; e com zero ou menos nao se chama a rede."""

    def test_a_visao(self) -> None:
        from kamba_agr.catalogo.visao import TECTO_DA_VISAO_S, VisaoPeloGateway

        llm = _Llm()
        visao = VisaoPeloGateway(cliente=llm)  # type: ignore[arg-type]
        foto = jpeg(b"P1", com_metadados=False)
        visao.extrair(A, foto)
        visao.extrair(A, foto, tecto_s=7.5)
        visao.extrair(A, foto, tecto_s=99.0)
        self.assertEqual(llm.tectos, [TECTO_DA_VISAO_S, 7.5, TECTO_DA_VISAO_S])
        with self.assertRaises(ErroDaVisao):
            visao.extrair(A, foto, tecto_s=0.0)
        self.assertEqual(len(llm.tectos), 3)

    def test_o_screening(self) -> None:
        from kamba_agr.tls.screening import TEMPO_MAXIMO_MS, ScreeningIndisponivelError, ScreeningPeloCom

        com = _Com({"decisao": "permitida", "regras": [], "versao_politica": "1", "confianca": 1, "publicavel": True})
        porta = ScreeningPeloCom(cliente=com, sujeito_tipo="produto", vertical="dono")  # type: ignore[arg-type]
        porta.screen(A, "s1", None, ("x",))
        porta.screen(A, "s1", None, ("x",), tecto_s=6.25)
        self.assertEqual([(c[1]["prazo_ms"], c[2]) for c in com.chamadas], [(TEMPO_MAXIMO_MS,) * 2, (6250, 6250)])
        with self.assertRaises(ScreeningIndisponivelError):
            porta.screen(A, "s1", None, ("x",), tecto_s=-1.0)
        self.assertEqual(len(com.chamadas), 2)

    def test_o_registo(self) -> None:
        from kamba_agr.tls.especificacoes import ErroDeBackend
        from kamba_agr.tls.registo_com import TEMPO_MAXIMO_MS, RegistoPeloCom
        from kamba_core.catalogo.extraccao import Campo
        from decimal import Decimal

        com = _Com()
        registo = RegistoPeloCom(cliente=com)  # type: ignore[arg-type]
        campos = {
            "nome": Campo(valor="Camisa", confianca=Decimal(1), fonte="dono_texto"),
            "preco_tipo": Campo(valor="sob_consulta", confianca=Decimal(1), fonte="dono_texto"),
        }
        registo.rascunho(A, "cat-1", campos)
        registo.rascunho(A, "cat-1", campos, tecto_s=1.2)
        self.assertEqual([c[2] for c in com.chamadas], [TEMPO_MAXIMO_MS, 1200])
        with self.assertRaises(ErroDeBackend) as erro:
            registo.rascunho(A, "cat-1", campos, tecto_s=0.0)
        self.assertEqual(erro.exception.codigo, UPSTREAM_TIMEOUT)
        self.assertEqual(len(com.chamadas), 2)


# ====================================================================== o grafo


class TestARetomaPeloGrafo(unittest.TestCase):
    def setUp(self) -> None:
        self.m = Mundo()
        self.addCleanup(self.m.fechar)

    def _bloqueada_sem_decisao(self) -> str:
        self.m.screening.falhar = True
        r = self.m.invocar("create_product_draft", {"media_id": "m1"})
        self.m.screening.falhar = False
        self.assertTrue(r.ok, r.error)
        self.assertTrue(r.data["retomavel"])
        return str(r.data["ingestao"])

    def test_o_screening_em_baixo_nao_diz_que_nao_pode_ser_publicado(self) -> None:
        dados = catalogo_tools.vista(self.m.repo.ler(A, self._bloqueada_sem_decisao()))  # type: ignore[arg-type]
        resposta = conversa._resposta_da_ingestao(dados)
        self.assertEqual(resposta["draft"]["botoes"], (regras.botao_de_retomar(dados["ingestao"]),))
        self.assertNotIn(conversa.MSG_CATEGORIA_RECUSADA, str(resposta))

    def test_uma_decisao_restritiva_continua_recusada_e_sem_botao(self) -> None:
        self.m.screening.decisao_forcada = None
        self.m.visao.texto = self.m.visao.texto.replace("vestuario", "cerveja")
        r = self.m.invocar("create_product_draft", {"media_id": "m1"})
        self.assertEqual(r.data["estado"], estados.BLOQUEADA_CATEGORIA)
        self.assertFalse(r.data["retomavel"])
        resposta = conversa._resposta_da_ingestao(r.data)
        self.assertFalse(resposta["draft"].get("botoes"))
        self.assertIn(conversa.MSG_CATEGORIA_RECUSADA, resposta["draft"]["texto"])
        # E o toque de retomar, forjado, nao levanta a decisao.
        self.m.turno(botao=regras.botao_de_retomar(r.data["ingestao"]))
        self.assertEqual(self.m.repo.ler(A, r.data["ingestao"]).estado, estados.BLOQUEADA_CATEGORIA)  # type: ignore[union-attr]

    def test_o_toque_retoma_e_a_ingestao_segue_para_as_perguntas(self) -> None:
        ingestao = self._bloqueada_sem_decisao()
        _final, texto, _botoes = self.m.turno(botao=regras.botao_de_retomar(ingestao))
        self.assertEqual(self.m.repo.ler(A, ingestao).estado, estados.A_PERGUNTAR)  # type: ignore[union-attr]
        self.assertIn(regras.referencia_do_produto(ingestao), texto)

    def test_a_referencia_leva_a_retomavel_ao_botao(self) -> None:
        """Depois de a camada cortar a foto, o estado lista-a, e a `PRD-…` da o botao."""
        ingestao = self._bloqueada_sem_decisao()
        _final, texto, _botoes = self.m.turno("os meus produtos")
        self.assertIn(regras.referencia_do_produto(ingestao), texto)
        _final, texto, botoes = self.m.turno(regras.referencia_do_produto(ingestao))
        self.assertIn(conversa.MSG_POR_VERIFICAR, texto)
        self.assertEqual(botoes, (regras.botao_de_retomar(ingestao),))

    def test_a_foto_cortada_pela_camada_diz_que_ainda_esta_a_preparar(self) -> None:
        async def cortada(_deps: Any, _estado: Any, _nome: str, _args: Any) -> ToolResult:
            return ToolResult(ok=False, error=ErroDeTool(codigo=UPSTREAM_TIMEOUT, detalhe="corte"))

        async def enfileirar(*_a: Any, **_k: Any) -> None:
            return None

        deps = mock.Mock(saida=mock.Mock(enfileirar=enfileirar))
        with mock.patch.object(conversa, "_invocar", cortada):
            resposta = asyncio.run(conversa._da_foto(deps, {"asset_id": str(uuid.uuid4()), "turn_id": "t1"}))
        self.assertIn(conversa.MSG_FOTO_EM_CURSO, str(resposta))


if __name__ == "__main__":
    unittest.main()
