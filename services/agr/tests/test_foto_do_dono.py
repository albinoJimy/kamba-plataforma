"""A foto real do catalogo do dono (KAM-231): o `asset_id`, a fonte e o rascunho.

Sem rede, sem base e sem imagens reais: a `media_assets` e o STO sao duplos
que leem o texto das instrucoes (a licao do «fake que decide por argumento»),
e as fotos sao os JPEG sinteticos do KAM-049 (`catalogo_apoio.jpeg`).
"""

from __future__ import annotations

import asyncio
import unittest
import uuid
from typing import Any
from unittest import mock

from apoio import invocacao_crua
from test_catalogo_dono import A, AGORA, B, CONTACTO_A, Mundo, _ate_ao_rascunho, jpeg  # noqa: F401
from test_vendedor import PERSONA

from kamba_agr.catalogo import fonte as fonte_mod
from kamba_agr.catalogo.fonte import (
    AssetDaFoto,
    FonteDoMed,
    FotoIndisponivelError,
    SQL_ASSET,
    SQL_OBJECTO_DA_MEDIA,
    ler_asset,
)
from kamba_agr.contexto import InvocacaoInvalidaError, ler_invocacao
from kamba_agr.estado import estado_inicial
from kamba_agr.tls import catalogo_tools
from kamba_agr.tls.registo_com import RegistoPeloCom
from kamba_agr.verticais.dono import build_graph as grafo_do_dono
from kamba_agr.verticais.dono import catalogo as conversa
from kamba_agr.verticais.dono import nos as nos_do_dono
from kamba_agr.verticais.vendedor import nos as nos_mod
from kamba_core.catalogo import estados
from kamba_core.catalogo.pipeline import ConfirmacaoDoDono
from kamba_core.storage.port import Ctx, ObjectRef

ASSET = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


# ====================================================================== os duplos


class _Cursor:
    def __init__(self, base: _Base) -> None:
        self._base = base
        self._linha: tuple[Any, ...] | None = None

    def execute(self, sql: str, parametros: tuple[Any, ...] = ()) -> None:
        self._base.instrucoes.append((sql, parametros))
        self._linha = self._base.responder(sql, parametros)

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._linha

    def close(self) -> None:
        return None


class _Base:
    """A `media_assets` de dois tenants, lida pelo **texto** da instrucao.

    O tenant do contexto (`set_config`) e o do predicado tem de coincidir com o
    da linha, como a RLS `FORCE` e o `tenant_id = %s`: um duplo que devolvesse a
    linha pelo argumento ficava verde com o predicado apagado.
    """

    def __init__(self, linhas: list[dict[str, Any]]) -> None:
        self.linhas = linhas
        self.instrucoes: list[tuple[str, tuple[Any, ...]]] = []
        self.contexto: str | None = None

    def cursor(self) -> _Cursor:
        return _Cursor(self)

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None

    def responder(self, sql: str, p: tuple[Any, ...]) -> tuple[Any, ...] | None:
        if "set_config" in sql:
            self.contexto = str(p[0])
            return (self.contexto,)
        visiveis = [l for l in self.linhas if l["tenant_id"] == self.contexto]
        if sql == SQL_ASSET:
            assert "tenant_id = %s::uuid AND asset_id = %s::uuid" in sql
            for l in visiveis:
                if l["tenant_id"] == p[0] and l["asset_id"] == p[1]:
                    return (l["media_id"], l["estado"], l["classe"], l["storage_ref"])
            return None
        if sql == SQL_OBJECTO_DA_MEDIA:
            assert "estado = 'armazenado' AND classe = 'media_imagem'" in sql
            for l in visiveis:
                if (
                    l["tenant_id"] == p[0]
                    and l["media_id"] == p[1]
                    and l["estado"] == "armazenado"
                    and l["classe"] == "media_imagem"
                    and l["storage_ref"]
                ):
                    return (l["storage_ref"],)
            return None
        raise AssertionError(f"instrucao inesperada: {sql}")


class _Storage:
    """O STO: so devolve uma chave do prefixo do tenant, como o `StorageProvider`."""

    def __init__(self, objectos: dict[str, bytes]) -> None:
        self.objectos = objectos

    def get(self, ctx: Ctx, ref: ObjectRef) -> Any:
        assert ref.key.startswith(f"t/{ctx.tenant_id}/"), "chave fora do tenant"
        corpo = self.objectos[ref.key]
        for i in range(0, len(corpo), 4):
            yield corpo[i : i + 4]


def _linha(tenant: str = A, **sobrepor: Any) -> dict[str, Any]:
    return {
        "tenant_id": tenant,
        "asset_id": ASSET,
        "media_id": "meta-123",
        "estado": "armazenado",
        "classe": "media_imagem",
        "storage_ref": f"t/{tenant}/media_imagem/2026/11/obj",
        **sobrepor,
    }


# ====================================================================== o contrato


class TestOContrato(unittest.TestCase):
    def test_o_asset_id_so_vem_numa_image_do_dono(self) -> None:
        inv = ler_invocacao(invocacao_crua(type="image", persona="dono", asset_id=ASSET))
        self.assertEqual(inv.asset_id, ASSET)
        self.assertEqual(estado_inicial(inv)["asset_id"], ASSET)
        for errado in (
            {"type": "text", "persona": "dono"},
            {"type": "image", "persona": "cliente"},
            {"type": "image"},
        ):
            with self.subTest(errado=errado), self.assertRaises(InvocacaoInvalidaError) as e:
                ler_invocacao(invocacao_crua(asset_id=ASSET, **errado))
            self.assertEqual(str(e.exception), "campo_invalido_asset_id")

    def test_um_asset_id_fora_da_forma_recusa(self) -> None:
        for valor in ("", None, ASSET.upper(), "media://" + ASSET, 7):
            with self.subTest(valor=valor), self.assertRaises(InvocacaoInvalidaError):
                ler_invocacao(invocacao_crua(type="image", persona="dono", asset_id=valor))

    def test_sem_asset_id_a_foto_nasce_sem_ele(self) -> None:
        inv = ler_invocacao(invocacao_crua(type="image", persona="dono"))
        self.assertIsNone(inv.asset_id)
        self.assertIsNone(estado_inicial(inv)["asset_id"])


# ====================================================================== a fonte


class TestAFonte(unittest.TestCase):
    def test_le_o_asset_no_tenant_dele(self) -> None:
        base = _Base([_linha()])
        self.assertEqual(ler_asset(base, A, ASSET), AssetDaFoto("meta-123", f"t/{A}/media_imagem/2026/11/obj"))
        self.assertEqual(base.contexto, A)

    def test_o_asset_de_outro_tenant_nao_se_le(self) -> None:
        base = _Base([_linha(tenant=B)])
        with self.assertRaises(FotoIndisponivelError):
            ler_asset(base, A, ASSET)

    def test_um_asset_sem_objecto_ou_que_nao_e_imagem_recusa(self) -> None:
        for sobrepor in (
            {"estado": "pendente", "storage_ref": None},
            {"estado": "rejeitado", "storage_ref": None},
            {"estado": "falhou", "storage_ref": None},
            {"classe": "media_audio"},
            {"classe": "media_documento"},
        ):
            with self.subTest(sobrepor=sobrepor), self.assertRaises(FotoIndisponivelError):
                ler_asset(_Base([_linha(**sobrepor)]), A, ASSET)

    def test_a_fonte_le_os_bytes_do_sto_pelo_media_id(self) -> None:
        corpo = jpeg(b"P1")
        base = _Base([_linha()])
        fonte = FonteDoMed(base, _Storage({f"t/{A}/media_imagem/2026/11/obj": corpo}))
        self.assertEqual(fonte.descarregar(A, "meta-123"), corpo)
        self.assertEqual(base.instrucoes[-1], (SQL_OBJECTO_DA_MEDIA, (A, "meta-123")))

    def test_a_fonte_nao_le_o_media_id_de_outro_tenant(self) -> None:
        base = _Base([_linha(tenant=B)])
        fonte = FonteDoMed(base, _Storage({f"t/{B}/media_imagem/2026/11/obj": b"x"}))
        with self.assertRaises(FotoIndisponivelError):
            fonte.descarregar(A, "meta-123")

    def test_a_fonte_corta_acima_do_tecto_do_med(self) -> None:
        base = _Base([_linha()])
        fonte = FonteDoMed(base, _Storage({f"t/{A}/media_imagem/2026/11/obj": b"x" * 9}), bytes_maximos=8)
        with self.assertRaises(FotoIndisponivelError):
            fonte.descarregar(A, "meta-123")

    def test_o_canario_sem_o_tenant_no_predicado_o_duplo_morde(self) -> None:
        # A ligacao mutada: a instrucao sem o predicado do tenant. O duplo le o
        # texto, e recusa-a — o ensaio da fonte nao fica verde com ele apagado.
        base = _Base([_linha()])
        mutada = SQL_ASSET.replace("tenant_id = %s::uuid AND ", "")
        with mock.patch.object(fonte_mod, "SQL_ASSET", mutada), self.assertRaises(AssertionError):
            ler_asset(base, A, ASSET)


# ====================================================================== o grafo


class _MundoDaFoto(Mundo):
    """O `Mundo` do KAM-119, com a `media_assets` por `asset_id`."""

    def __init__(self, assets: dict[tuple[str, str], str], medias: dict[str, bytes]) -> None:
        super().__init__(medias=medias)
        self.assets = assets
        remendo = mock.patch.object(catalogo_tools, "ler_asset", self._ler_asset)
        remendo.start()
        self._remendos.append(remendo)

    def _ler_asset(self, _ligacao: Any, tenant: str, asset_id: str) -> AssetDaFoto:
        media_id = self.assets.get((tenant, asset_id))
        if media_id is None:
            raise FotoIndisponivelError("a foto nao existe neste tenant")
        return AssetDaFoto(media_id=media_id, storage_ref=f"t/{tenant}/media_imagem/x")

    def foto(self, asset_id: str | None, *, tenant: str = A) -> tuple[dict[str, Any], str, tuple[str, ...]]:
        deps = nos_mod.Dependencias(
            tools=self.camada,
            saida=self.saida,
            persona=PERSONA,
            accoes_do_dono=self.accoes,
            tools_permitidas=nos_do_dono.TOOLS_DO_DONO,
        )
        troca: dict[str, Any] = {"persona": "dono", "tenant_id": tenant, "contact_id": CONTACTO_A, "type": "image"}
        if asset_id is not None:
            troca["asset_id"] = asset_id
        estado = estado_inicial(ler_invocacao(invocacao_crua(**troca)))
        final = asyncio.run(grafo_do_dono(deps).ainvoke(estado))
        texto, _chave, botoes = self.saida.enviadas[-1]
        return final, texto, tuple(botoes)


class TestAFotoPeloGrafo(unittest.TestCase):
    def setUp(self) -> None:
        self.outro = str(uuid.uuid4())
        self.m = _MundoDaFoto(
            {(A, ASSET): "meta-1", (A, self.outro): "meta-2"},
            {"meta-1": jpeg(b"P1"), "meta-2": jpeg(b"P2")},
        )
        self.addCleanup(self.m.fechar)

    def test_uma_foto_do_dono_da_um_rascunho_e_a_primeira_pergunta(self) -> None:
        final, texto, _ = self.m.foto(ASSET)
        self.assertEqual(final["intent"], "catalogo")
        (ingestao,) = self.m.repo.todas()
        self.assertEqual(ingestao.media_id_meta, "meta-1")
        self.assertEqual(ingestao.estado, estados.A_PERGUNTAR)
        self.assertNotIn(conversa.MSG_FOTO_POR_LIGAR, texto)
        self.assertIn("PRD-", texto)

    def test_o_aviso_sai_antes_do_resumo_com_chave_propria(self) -> None:
        """P3 (opcao A): «estou a preparar» antes da tool de 25 s, e o resumo depois."""
        antes = len(self.m.saida.enviadas)
        self.m.foto(ASSET)
        enviadas = self.m.saida.enviadas[antes:]
        self.assertEqual(len(enviadas), 2)
        (aviso, chave_do_aviso, _), (resumo, chave_do_resumo, _) = enviadas
        self.assertEqual(aviso, conversa.MSG_A_PREPARAR)
        self.assertTrue(chave_do_aviso.endswith(f":{conversa.SEQ_DO_AVISO}"))
        self.assertTrue(chave_do_resumo.endswith(":0"))
        self.assertEqual(chave_do_aviso.rsplit(":", 1)[0], chave_do_resumo.rsplit(":", 1)[0])
        self.assertIn("PRD-", resumo)

    def test_sem_foto_armazenada_nao_ha_aviso(self) -> None:
        antes = len(self.m.saida.enviadas)
        self.m.foto(None)
        enviadas = self.m.saida.enviadas[antes:]
        self.assertEqual(len(enviadas), 1)
        self.assertIn(conversa.MSG_FOTO_POR_LIGAR, enviadas[0][0])
        self.assertNotIn(conversa.MSG_A_PREPARAR, enviadas[0][0])

    def test_a_mesma_foto_duas_vezes_e_um_rascunho(self) -> None:
        self.m.foto(ASSET)
        self.m.foto(ASSET)
        self.assertEqual(len(self.m.repo.todas()), 1)

    def test_dez_fotos_dao_dez_rascunhos(self) -> None:
        assets = {(A, str(uuid.uuid4())): f"meta-{n}" for n in range(10)}
        m = _MundoDaFoto(assets, {f"meta-{n}": jpeg(f"P{n}".encode()) for n in range(10)})
        self.addCleanup(m.fechar)
        for _tenant, asset in assets:
            m.foto(asset)
        ingestoes = m.repo.todas()
        self.assertEqual(len(ingestoes), 10)
        self.assertEqual(len({i.id for i in ingestoes}), 10)
        self.assertEqual({i.media_id_meta for i in ingestoes}, set(assets.values()))

    def test_uma_foto_sem_asset_id_diz_que_nao_chegou(self) -> None:
        _final, texto, _ = self.m.foto(None)
        self.assertIn(conversa.MSG_FOTO_POR_LIGAR, texto)
        self.assertEqual(self.m.repo.todas(), ())

    def test_o_asset_de_outro_tenant_nao_vira_rascunho(self) -> None:
        _final, texto, _ = self.m.foto(ASSET, tenant=B)
        self.assertIn(conversa.MSG_FOTO_POR_LIGAR, texto)
        self.assertEqual(self.m.repo.todas(), ())

    def test_um_asset_id_pela_tool_so_com_a_forma_de_um_uuid(self) -> None:
        r = self.m.invocar("create_product_draft", {"asset_id": "meta-1"})
        self.assertFalse(r.ok)
        r = self.m.invocar("create_product_draft", {"asset_id": ASSET, "media_id": "meta-1"})
        self.assertFalse(r.ok)
        self.assertEqual(self.m.repo.todas(), ())


# ====================================================================== o stock


class TestOStockNaPublicacao(unittest.TestCase):
    def test_a_quantidade_do_dono_vai_com_a_publicacao(self) -> None:
        m = Mundo(medias={"m1": jpeg(b"P1")})
        self.addCleanup(m.fechar)
        ingestao = m.invocar("create_product_draft", {"media_id": "m1"}).data["ingestao"]
        r = _ate_ao_rascunho(m, ingestao)
        _f, _t, botoes = m.turno(botao=f"confirm:{r.data['action_id']}")
        self.assertEqual(len(m.registo.publicados), 1)
        sku = m.registo.publicados[0][1]
        self.assertEqual(m.registo.stocks[sku], 5)

    def test_o_corpo_da_publicacao_leva_o_stock_so_quando_o_ha(self) -> None:
        chamadas: list[dict[str, Any]] = []

        class _Com:
            def chamar(self, rota: str, ctx: Any, corpo: dict[str, Any], timeout_ms: int) -> dict[str, Any]:
                chamadas.append(corpo)
                return {}

        registo = RegistoPeloCom(cliente=_Com())  # type: ignore[arg-type]
        confirmacao = ConfirmacaoDoDono(actor=CONTACTO_A, em=AGORA, versao_texto="v1")
        registo.publicar(A, "PRD1", confirmacao, stock=5)
        registo.publicar(A, "PRD1", confirmacao)
        self.assertEqual(chamadas[0]["stock"], 5)
        self.assertNotIn("stock", chamadas[1])
        for errado in (-1, True):
            with self.subTest(errado=errado), self.assertRaises(Exception):
                registo.publicar(A, "PRD1", confirmacao, stock=errado)


if __name__ == "__main__":
    unittest.main()
