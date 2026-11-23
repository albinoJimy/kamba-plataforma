"""A foto do dono pelo painel (KAM-243), do lado do AGR.

O painel guarda a foto pelo MED (no `onboarding-web`) e invoca o AGR com a
credencial **dele** (`agr_painel_token`), num turno `image` com o `asset_id`,
sem `message_id` e com o `wamid` `painel.{asset_id}.{envio}`. Aqui mede-se:

- a admissao: essa forma passa com a credencial do painel, e qualquer outra da
  o mesmo 401 de uma credencial errada (criterio 2);
- o canal: o turno de uma foto do painel responde pelo `painel`, e o de uma foto
  do WhatsApp continua a responder pelo WhatsApp;
- a prova de que a foto e do painel e o contacto e o dono, antes do grafo
  (achado 1 da revisao adversarial): sem ela, 400 `invocacao_invalida`;
- a ponta a ponta do lado do AGR: a invocacao que o painel monta, admitida, da
  **um** rascunho e a primeira pergunta, e a mesma foto duas vezes da **um**.
"""

from __future__ import annotations

import asyncio
import json
import unittest
import uuid
from typing import Any

from apoio import CREDENCIAL, como_json, invocacao_crua, pedir
from test_catalogo_dono import A, B, CONTACTO_A, jpeg
from test_foto_do_dono import ASSET, _MundoDaFoto
from test_mensagens import (
    CREDENCIAL_DO_PAINEL,
    GrafoQueRegista,
    aplicacao,
    correr_lote,
    invocacao_do_painel,
)
from apoio import TrancaFalsa
from test_saida import Base as BaseDeRespostas
from test_saida import Ligacao as LigacaoDeRespostas
from test_vendedor import PERSONA

from kamba_agr.api_interna import TIPO_DA_FOTO_DO_PAINEL, invocacao_do_painel_admitida
from kamba_agr.admissao import Admissao, Tectos
from kamba_agr.contexto import PREFIXO_DO_WAMID_DO_PAINEL, ler_invocacao, wamid_da_foto_do_painel
from kamba_agr.mensagens import (
    CODIGO_FOTO_NAO_ENCONTRADA,
    SQL_LER_FOTO_DO_PAINEL,
    FotoDoPainelNaoEncontradaError,
    LeituraDeMensagensPorLigarError,
)
from kamba_agr.estado import estado_inicial
from kamba_agr.metricas import METRICAS
from kamba_agr.saida import SaidaPorEvento, canal_do_turno
from kamba_agr.turno import DesfechoDoTurno, ExecutorDeTurnos, Palavra, turno_da_foto_do_painel
from kamba_agr.verticais.dono import build_graph as grafo_do_dono
from kamba_agr.verticais.dono import catalogo as conversa
from kamba_agr.verticais.dono import nos as nos_do_dono
from kamba_agr.verticais.vendedor import nos as nos_mod
from kamba_core.catalogo import estados


def foto_do_painel(**sobrepor: Any) -> dict[str, Any]:
    """A invocacao que o `invocacaoDaFoto` do core-ts monta: `image`, persona
    `dono`, o `asset_id`, sem `message_id`, e o `wamid` `painel.{asset_id}.{envio}`."""
    asset_id = sobrepor.pop("asset_id", str(uuid.uuid4()))
    campos: dict[str, Any] = {
        "persona": "dono",
        "type": "image",
        "asset_id": asset_id,
        "wamid": f"painel.{asset_id}.{uuid.uuid4().hex}",
    }
    campos.update(sobrepor)
    return invocacao_crua(**campos)


def executor_da_foto(grafo: GrafoQueRegista, *, e_do_dono: bool = True, porta: bool = True) -> ExecutorDeTurnos:
    """O `ExecutorDeTurnos` real, com a porta da foto do painel a dizer `e_do_dono`."""
    lidas: list[Any] = []

    async def ler_palavra(_inv: Any) -> Palavra:
        return Palavra(modo="bot", handoff_a_espera=False)

    async def reencaminhar(_invs: Any) -> None:
        return None

    async def ler_foto(invocacao: Any) -> bool:
        lidas.append(invocacao)
        return e_do_dono

    executor = ExecutorDeTurnos(
        trancas=TrancaFalsa(),
        ler_palavra=ler_palavra,
        grafos=lambda _inv: grafo,
        reencaminhar=reencaminhar,
        admissao=Admissao(tectos=Tectos(coalescencia_ms=0)),
        ler_foto_do_painel=ler_foto if porta else None,
    )
    executor.lidas = lidas  # type: ignore[attr-defined]
    return executor


class TestAForma(unittest.TestCase):
    def test_o_prefixo_e_o_tipo(self) -> None:
        self.assertEqual(PREFIXO_DO_WAMID_DO_PAINEL, "painel.")
        self.assertEqual(TIPO_DA_FOTO_DO_PAINEL, "image")

    def test_a_foto_do_painel_e_admitida(self) -> None:
        self.assertTrue(invocacao_do_painel_admitida(ler_invocacao(foto_do_painel())))

    def test_o_texto_do_painel_continua_admitido(self) -> None:
        self.assertTrue(invocacao_do_painel_admitida(ler_invocacao(invocacao_do_painel())))

    def test_outra_forma_nao(self) -> None:
        asset = str(uuid.uuid4())
        casos = {
            "o wamid de outro asset": foto_do_painel(
                asset_id=asset, wamid=f"painel.{uuid.uuid4()}.{uuid.uuid4().hex}"
            ),
            "o wamid sem envio": foto_do_painel(asset_id=asset, wamid=f"painel.{asset}"),
            "o envio fora da forma": foto_do_painel(asset_id=asset, wamid=f"painel.{asset}.x"),
            "o wamid do whatsapp": foto_do_painel(
                wamid="wamid.HBgMMjQ0OTAwMDAwMDAwFQIAEhgg" + uuid.uuid4().hex[:8]
            ),
            "o wamid do message_id": foto_do_painel(
                asset_id=asset, message_id=(m := str(uuid.uuid4())), wamid=f"painel.{m}"
            ),
            "asset e message_id juntos": foto_do_painel(
                asset_id=asset, message_id=str(uuid.uuid4())
            ),
            "image sem asset nem message_id": invocacao_crua(
                persona="dono", type="image", wamid=f"painel.{asset}"
            ),
            "image com message_id e sem asset": invocacao_do_painel(type="image"),
        }
        for nome, corpo in casos.items():
            with self.subTest(nome):
                self.assertFalse(invocacao_do_painel_admitida(ler_invocacao(corpo)))


class TestARota(unittest.IsolatedAsyncioTestCase):
    """Criterio 2: com a credencial do painel, a foto passa, e outra forma da a mesma 401."""

    async def asyncSetUp(self) -> None:
        METRICAS.repor()
        self.corridas: list[Any] = []

        async def executar(invocacao):
            self.corridas.append(invocacao)
            return DesfechoDoTurno(desfecho="executado", turn_id=invocacao.turn_id)

        self.app = aplicacao(executar)

    async def pedir(self, corpo: dict[str, Any], credencial: str | None):
        cabecalhos = {} if credencial is None else {"x-kamba-interno": credencial}
        return await pedir(self.app, "/internal/turn", "POST", como_json(corpo), cabecalhos)

    async def test_a_foto_do_painel_corre_o_turno_com_o_asset_id(self) -> None:
        corpo = foto_do_painel()
        estado, _, resposta = await self.pedir(corpo, CREDENCIAL_DO_PAINEL)
        self.assertEqual(estado, 200)
        self.assertEqual(json.loads(resposta)["outcome"], "executado")
        (corrida,) = self.corridas
        self.assertEqual(corrida.asset_id, corpo["asset_id"])
        self.assertIsNone(corrida.message_id)
        self.assertEqual(corrida.persona, "dono")

    async def test_outra_forma_e_a_mesma_401_e_nao_corre(self) -> None:
        asset = str(uuid.uuid4())
        casos = {
            "o wamid de outro asset": foto_do_painel(wamid=f"painel.{uuid.uuid4()}.{uuid.uuid4().hex}"),
            "o wamid sem envio": foto_do_painel(asset_id=asset, wamid=f"painel.{asset}"),
            "o wamid do whatsapp": foto_do_painel(
                wamid="wamid.HBgMMjQ0OTAwMDAwMDAwFQIAEhgg" + uuid.uuid4().hex[:8]
            ),
            "asset e message_id juntos": foto_do_painel(asset_id=asset, message_id=str(uuid.uuid4())),
            "image sem asset": invocacao_crua(persona="dono", type="image", wamid=f"painel.{asset}"),
        }
        _, _, referencia = await self.pedir(invocacao_crua(), None)
        for nome, corpo in casos.items():
            with self.subTest(nome):
                ler_invocacao(corpo)
                estado, _, resposta = await self.pedir(corpo, CREDENCIAL_DO_PAINEL)
                self.assertEqual(estado, 401)
                self.assertEqual(resposta, referencia)
        self.assertEqual(self.corridas, [])

    async def test_uma_foto_de_cliente_nem_chega_a_admissao(self) -> None:
        # O contrato recusa um `asset_id` fora da persona `dono` (400), antes da
        # regra da credencial: um cliente nao cria rascunhos de catalogo.
        estado, _, resposta = await self.pedir(foto_do_painel(persona="cliente"), CREDENCIAL_DO_PAINEL)
        self.assertEqual(estado, 400)
        self.assertEqual(json.loads(resposta)["error_code"], "campo_invalido_asset_id")
        self.assertEqual(self.corridas, [])

    async def test_o_shim_continua_a_passar_a_foto_do_whatsapp(self) -> None:
        corpo = invocacao_crua(persona="dono", type="image", asset_id=str(uuid.uuid4()))
        estado, _, _ = await self.pedir(corpo, CREDENCIAL)
        self.assertEqual(estado, 200)
        estado, _, _ = await self.pedir(corpo, CREDENCIAL_DO_PAINEL)
        self.assertEqual(estado, 401, "o wamid da Meta nao e um turno do painel")


class TestOCanal(unittest.TestCase):
    """A foto do painel responde pelo painel; a do WhatsApp, pelo WhatsApp."""

    def correr(self, corpo: dict[str, Any]) -> tuple[BaseDeRespostas, list[str | None]]:
        respostas = BaseDeRespostas()
        porta = SaidaPorEvento(lambda: LigacaoDeRespostas(respostas), canal_de=canal_do_turno)

        async def responder(estado: dict[str, Any]) -> None:
            await porta.enfileirar(estado, "Recebi a foto.", chave=f"{estado['turn_id']}:1")

        grafo = GrafoQueRegista(ao_correr=responder)
        invocacao = ler_invocacao(corpo)
        asyncio.run(correr_lote(executor_da_foto(grafo), [invocacao]))
        return respostas, grafo.canais

    def test_o_reconhecimento(self) -> None:
        self.assertTrue(turno_da_foto_do_painel(ler_invocacao(foto_do_painel())))
        self.assertFalse(
            turno_da_foto_do_painel(
                ler_invocacao(invocacao_crua(persona="dono", type="image", asset_id=str(uuid.uuid4())))
            )
        )
        self.assertFalse(
            turno_da_foto_do_painel(ler_invocacao(foto_do_painel(wamid=f"painel.{uuid.uuid4()}.{uuid.uuid4().hex}")))
        )
        self.assertFalse(turno_da_foto_do_painel(ler_invocacao(invocacao_do_painel())))

    def test_a_foto_do_painel_responde_pelo_painel(self) -> None:
        respostas, canais = self.correr(foto_do_painel())
        self.assertEqual(canais, ["painel"])
        self.assertEqual(respostas.respostas[0]["canal"], "painel")

    def test_a_foto_do_whatsapp_responde_pelo_whatsapp(self) -> None:
        corpo = invocacao_crua(persona="dono", type="image", asset_id=str(uuid.uuid4()))
        respostas, canais = self.correr(corpo)
        self.assertEqual(canais, [None])
        self.assertEqual(respostas.respostas[0]["canal"], "whatsapp")


class TestAProvaAntesDoGrafo(unittest.IsolatedAsyncioTestCase):
    """Achado 1 da revisao adversarial: a credencial do painel nao corre o dono
    para um contacto que nao e o dono, nem com uma foto que nao e a do painel."""

    async def test_uma_foto_que_nao_se_prova_da_400_e_nao_corre_o_grafo(self) -> None:
        METRICAS.repor()
        grafo = GrafoQueRegista()
        executor = executor_da_foto(grafo, e_do_dono=False)
        corpo = foto_do_painel()
        estado, _, resposta = await pedir(
            aplicacao(executor.correr),
            "/internal/turn",
            "POST",
            como_json(corpo),
            {"x-kamba-interno": CREDENCIAL_DO_PAINEL},
        )
        self.assertEqual(estado, 400)
        self.assertEqual(
            json.loads(resposta),
            {"outcome": "invocacao_invalida", "error_code": CODIGO_FOTO_NAO_ENCONTRADA},
        )
        self.assertNotIn(corpo["asset_id"], resposta.decode())
        self.assertEqual(grafo.entradas, [])
        self.assertEqual([i.asset_id for i in executor.lidas], [corpo["asset_id"]])

    async def test_a_foto_que_se_prova_corre_o_turno(self) -> None:
        grafo = GrafoQueRegista()
        estado, _, resposta = await pedir(
            aplicacao(executor_da_foto(grafo).correr),
            "/internal/turn",
            "POST",
            como_json(foto_do_painel()),
            {"x-kamba-interno": CREDENCIAL_DO_PAINEL},
        )
        self.assertEqual(estado, 200)
        self.assertEqual(json.loads(resposta)["outcome"], "executado")
        self.assertEqual(len(grafo.entradas), 1)

    async def test_sem_a_porta_o_turno_nao_corre(self) -> None:
        grafo = GrafoQueRegista()
        (resultado,) = await correr_lote(
            executor_da_foto(grafo, porta=False), [ler_invocacao(foto_do_painel())]
        )
        self.assertIsInstance(resultado, LeituraDeMensagensPorLigarError)
        self.assertEqual(grafo.entradas, [])

    async def test_a_foto_do_whatsapp_nao_passa_pela_porta(self) -> None:
        grafo = GrafoQueRegista()
        executor = executor_da_foto(grafo, e_do_dono=False)
        corpo = invocacao_crua(persona="dono", type="image", asset_id=str(uuid.uuid4()))
        (resultado,) = await correr_lote(executor, [ler_invocacao(corpo)])
        self.assertNotIsInstance(resultado, BaseException)
        self.assertEqual(executor.lidas, [])

    def test_o_erro_e_uma_invocacao_invalida_com_codigo_proprio(self) -> None:
        erro = FotoDoPainelNaoEncontradaError()
        self.assertEqual(erro.codigo, CODIGO_FOTO_NAO_ENCONTRADA)

    def test_a_instrucao_le_a_linha_desta_conversa_do_dono(self) -> None:
        # A semantica mede-se contra o PostgreSQL (`db/tests_agr/test_foto_do_painel.py`);
        # aqui, que nenhuma das condicoes da prova saiu do texto.
        sql = " ".join(SQL_LER_FOTO_DO_PAINEL.split())
        for condicao in (
            "a.asset_id = %s::uuid",
            "a.tenant_id = %s::uuid",
            "a.contact_id = %s::uuid",
            "a.conversation_id = %s::uuid",
            "a.estado = 'armazenado'",
            "a.classe = 'media_imagem'",
            "starts_with(a.media_id, 'painel.')",
            "c.papel = 'dono'",
            "c.erased_at IS NULL",
            "c.merged_into IS NULL",
        ):
            with self.subTest(condicao):
                self.assertIn(condicao, sql)

    def test_o_envio_tem_a_forma_de_32_hexadecimais(self) -> None:
        asset = str(uuid.uuid4())
        self.assertTrue(wamid_da_foto_do_painel(f"painel.{asset}.{uuid.uuid4().hex}", asset))
        for wamid in (f"painel.{asset}", f"painel.{asset}.", f"painel.{asset}.{uuid.uuid4()}", f"painel.{uuid.uuid4()}.{uuid.uuid4().hex}"):
            with self.subTest(wamid):
                self.assertFalse(wamid_da_foto_do_painel(wamid, asset))


class TestDoPainelAoRascunho(unittest.TestCase):
    """A invocacao do painel, admitida, chega ao `create_product_draft` como a do WhatsApp."""

    def setUp(self) -> None:
        self.m = _MundoDaFoto({(A, ASSET): "painel.media-1"}, {"painel.media-1": jpeg(b"P1")})
        self.addCleanup(self.m.fechar)

    def foto(self, tenant: str = A) -> tuple[dict[str, Any], str]:
        corpo = foto_do_painel(asset_id=ASSET, tenant_id=tenant, contact_id=CONTACTO_A)
        invocacao = ler_invocacao(corpo)
        self.assertTrue(invocacao_do_painel_admitida(invocacao))
        deps = nos_mod.Dependencias(
            tools=self.m.camada,
            saida=self.m.saida,
            persona=PERSONA,
            accoes_do_dono=self.m.accoes,
            tools_permitidas=nos_do_dono.TOOLS_DO_DONO,
        )
        final = asyncio.run(grafo_do_dono(deps).ainvoke(estado_inicial(invocacao)))
        texto, _chave, _botoes = self.m.saida.enviadas[-1]
        return final, texto

    def test_uma_foto_pelo_painel_da_um_rascunho_e_a_primeira_pergunta(self) -> None:
        final, texto = self.foto()
        self.assertEqual(final["intent"], "catalogo")
        (ingestao,) = self.m.repo.todas()
        self.assertEqual(ingestao.media_id_meta, "painel.media-1")
        self.assertEqual(ingestao.estado, estados.A_PERGUNTAR)
        self.assertIn("PRD-", texto)
        avisos = [t for t, _c, _b in self.m.saida.enviadas if t == conversa.MSG_A_PREPARAR]
        self.assertEqual(len(avisos), 1, "o «estou a preparar» sai antes do resumo, como no WhatsApp")

    def test_a_mesma_foto_pelo_painel_duas_vezes_e_um_rascunho(self) -> None:
        self.foto()
        self.foto()
        self.assertEqual(len(self.m.repo.todas()), 1)

    def test_o_asset_do_tenant_a_numa_sessao_de_b_nao_vira_rascunho(self) -> None:
        _final, texto = self.foto(tenant=B)
        self.assertIn(conversa.MSG_FOTO_POR_LIGAR, texto)
        self.assertEqual(self.m.repo.todas(), ())


if __name__ == "__main__":
    unittest.main()
