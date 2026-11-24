"""A pagina Social do painel, do lado do AGR (KAM-246), sem base.

As duas rotas `/internal/social/itens` e `/internal/social/descarga`, com a
credencial do painel, o STO *fake* e a primitiva da ligacao do KAM-098. A
leitura dos itens contra o PostgreSQL (a RLS) mede-a o
`db/tests_agr/test_social_do_dono.py`; o X-01 das duas rotas, o *gate* 6.

**Canario**: `test_a_lista_traz_a_imagem_a_legenda_a_nota_e_a_ligacao`. Sem ele,
as recusas abaixo passavam com uma rota que recusa tudo.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import unittest
from typing import Any

from apoio import pedir
from kamba_agr.app import create_app
from kamba_agr.social import painel
from kamba_agr.social.publicacao import NOTA_DO_ROTULO_DE_IA
from kamba_agr.social.repositorio import APROVADO, ENTREGUE, Item
from kamba_core.offboarding.exportacao import VALIDADE_DA_LIGACAO, ligacao_assinada
from kamba_core.storage import Ctx, ObjectMeta, ObjectRef
from kamba_core.storage.fake import criar_storage_fake

A = "11111111-1111-4111-8111-111111111111"
B = "22222222-2222-4222-8222-222222222222"
AGORA = datetime.datetime(2026, 11, 23, 12, 0, tzinfo=datetime.UTC)
CREDENCIAL = "credencial-do-painel-de-ensaio"
CHAVE = b"k" * 32
ANTERIOR = b"a" * 32
JPEG = b"\xff\xd8\xff\xe0arte"


class Mundo:
    def __init__(self) -> None:
        self.relogio = AGORA
        self.fake = criar_storage_fake(lambda: self.relogio)
        self.storage = self.fake.storage
        self.itens: dict[str, list[Item]] = {A: [], B: []}
        self.chaves: list[bytes] = [CHAVE]
        self.painel = painel.PainelDoSocial(
            itens=lambda tenant: tuple(self.itens.get(tenant, [])),
            assinador=self.storage,
            chaves=lambda: list(self.chaves),
            relogio=lambda: self.relogio,
        )

    def arte(self, tenant: str, estado: str = APROVADO, sufixo: str = "1") -> Item:
        chave = f"t/{tenant}/arte/2026/11/0b1c2d3e-4f50-4617-8a9b-0c1d2e3f4a5{sufixo}"
        self.storage.put(
            Ctx(tenant),
            chave,
            JPEG,
            ObjectMeta("image/jpeg", "arte", AGORA + datetime.timedelta(days=90)),
        )
        item = Item(
            content_item_id=f"0b1c2d3e-4f50-4617-8a9b-0c1d2e3f4a5{sufixo}",
            tenant_id=tenant,
            calendar_id="0b1c2d3e-4f50-4617-8a9b-0c1d2e3f4a60",
            semana_iso="2026-W48",
            tipo="produto",
            tema="Vestidos novos",
            agendado_at=AGORA,
            legenda="Vestidos novos para a semana.",
            estado=estado,
            arte_ref=chave,
        )
        self.itens[tenant].append(item)
        return item


def _app(mundo: Mundo | None, credencial: str | None = CREDENCIAL) -> Any:
    return create_app(
        rotas_internas=painel.rotas(
            credencial=None if credencial is None else (lambda: credencial),
            painel=None if mundo is None else mundo.painel,
        )
    )


def _pedir(app: Any, rota: str, corpo: Any, cabecalhos: dict[str, str] | None = None) -> tuple[int, dict]:
    estado, _, cru = asyncio.run(
        pedir(
            app,
            rota,
            "POST",
            json.dumps(corpo).encode(),
            {"x-kamba-interno": CREDENCIAL} if cabecalhos is None else cabecalhos,
        )
    )
    return estado, json.loads(cru) if cru else {}


class TestALista(unittest.TestCase):
    def setUp(self) -> None:
        self.mundo = Mundo()

    def test_a_lista_traz_a_imagem_a_legenda_a_nota_e_a_ligacao(self) -> None:
        self.mundo.arte(A, APROVADO, "1")
        self.mundo.arte(A, ENTREGUE, "2")
        estado, corpo = _pedir(_app(self.mundo), painel.ROTA_DOS_ITENS, {"tenant_id": A})
        self.assertEqual(estado, 200)
        itens = corpo["itens"]
        self.assertEqual([i["estado"] for i in itens], [APROVADO, ENTREGUE])
        for item in itens:
            self.assertRegex(item["referencia"], r"^SOC-[A-HJ-NP-R]{8}$")
            self.assertEqual(item["legenda"], "Vestidos novos para a semana.")
            self.assertEqual(item["nota"], NOTA_DO_ROTULO_DE_IA)
            # A imagem e um URL do STO de cinco minutos, que abre os bytes da arte.
            self.assertEqual(self.mundo.fake.buscar(item["imagem"]).corpo, JPEG)
            # A ligacao e a do KAM-098, e abre so para o tenant dela.
            self.assertTrue(self.mundo.painel.abrir(A, item["ligacao"]))

    def test_o_tenant_de_b_nao_ve_a_arte_de_a(self) -> None:
        self.mundo.arte(A)
        estado, corpo = _pedir(_app(self.mundo), painel.ROTA_DOS_ITENS, {"tenant_id": B})
        self.assertEqual((estado, corpo), (200, {"itens": []}))

    def test_sem_chave_da_ligacao_responde_503(self) -> None:
        self.mundo.arte(A)
        self.mundo.chaves = []
        estado, corpo = _pedir(_app(self.mundo), painel.ROTA_DOS_ITENS, {"tenant_id": A})
        self.assertEqual((estado, corpo["outcome"]), (503, "painel_por_ligar"))

    def test_uma_chave_curta_nao_assina(self) -> None:
        chaves = painel.anel_da_ligacao(lambda: ("curta", None))
        with self.assertRaises(painel.PainelPorLigarError):
            chaves()
        self.assertEqual(painel.anel_da_ligacao(lambda: ("x" * 32, None))(), [b"x" * 32])


class TestADescarga(unittest.TestCase):
    def setUp(self) -> None:
        self.mundo = Mundo()
        self.item = self.mundo.arte(A)
        self.ligacao = ligacao_assinada(CHAVE, A, self.item.arte_ref or "", AGORA)

    def _abrir(self, tenant: str, ligacao: str) -> tuple[int, dict]:
        return _pedir(_app(self.mundo), painel.ROTA_DA_DESCARGA, {"tenant_id": tenant, "ligacao": ligacao})

    def test_cada_abertura_assina_um_url_de_cinco_minutos(self) -> None:
        estado, corpo = self._abrir(A, self.ligacao)
        self.assertEqual(estado, 200)
        self.assertEqual(self.mundo.fake.buscar(corpo["url"]).corpo, JPEG)
        # Seis minutos depois o URL ja nao serve, e a ligacao continua a abrir outro.
        self.mundo.relogio = AGORA + datetime.timedelta(minutes=6)
        self.assertNotEqual(self.mundo.fake.buscar(corpo["url"]).estado, 200)
        estado, outro = self._abrir(A, self.ligacao)
        self.assertEqual(estado, 200)
        self.assertEqual(self.mundo.fake.buscar(outro["url"]).corpo, JPEG)

    def test_expirada_adulterada_ou_de_outro_tenant_da_o_mesmo_404(self) -> None:
        corpo_b64, mac = self.ligacao.split(".")
        adulterada = f"{corpo_b64}.{'A' if mac[0] != 'A' else 'B'}{mac[1:]}"
        de_outra_chave = ligacao_assinada(b"z" * 32, A, self.item.arte_ref or "", AGORA)
        respostas = [self._abrir(B, self.ligacao), self._abrir(A, adulterada), self._abrir(A, de_outra_chave)]
        self.mundo.relogio = AGORA + VALIDADE_DA_LIGACAO + datetime.timedelta(seconds=1)
        respostas.append(self._abrir(A, self.ligacao))
        self.assertEqual({json.dumps(r, sort_keys=True) for r in respostas}, {json.dumps([404, {"outcome": "ligacao_recusada"}])})

    def test_sem_chave_ou_com_o_cofre_a_falhar_a_descarga_e_503_e_nao_404(self) -> None:
        def cofre_em_falha() -> list[bytes]:
            raise RuntimeError("segredo revogado")

        for chaves in (lambda: [], cofre_em_falha):
            self.mundo.painel._chaves = chaves
            for rota, corpo in (
                (painel.ROTA_DOS_ITENS, {"tenant_id": A}),
                (painel.ROTA_DA_DESCARGA, {"tenant_id": A, "ligacao": self.ligacao}),
            ):
                self.assertEqual(_pedir(_app(self.mundo), rota, corpo), (503, {"outcome": "painel_por_ligar"}))

    def test_a_rotacao_nao_mata_as_ligacoes_vivas(self) -> None:
        self.mundo.chaves = [b"n" * 32, CHAVE]
        self.assertEqual(self._abrir(A, self.ligacao)[0], 200)
        self.mundo.chaves = [b"n" * 32]
        self.assertEqual(self._abrir(A, self.ligacao)[0], 404)


class TestAsRecusasDaRota(unittest.TestCase):
    def test_sem_credencial_ou_com_outra_401_antes_de_ler_o_corpo(self) -> None:
        mundo = Mundo()
        for rota in (painel.ROTA_DOS_ITENS, painel.ROTA_DA_DESCARGA):
            for cabecalhos in ({}, {"x-kamba-interno": "outra"}):
                estado, corpo = _pedir(_app(mundo), rota, "nao e um corpo", cabecalhos)
                self.assertEqual((estado, corpo), (401, {"outcome": "nao_autorizado"}))
            # Sem credencial no cofre, fecha.
            estado, _ = _pedir(_app(mundo, credencial=None), rota, {"tenant_id": A})
            self.assertEqual(estado, 401)

    def test_um_corpo_fora_da_forma_e_400(self) -> None:
        mundo = Mundo()
        for corpo in ({}, {"tenant_id": "x"}, {"tenant_id": A, "mais": 1}, [A], {"tenant_id": 3}):
            self.assertEqual(_pedir(_app(mundo), painel.ROTA_DOS_ITENS, corpo)[0], 400, corpo)
        self.assertEqual(
            _pedir(_app(mundo), painel.ROTA_DA_DESCARGA, {"tenant_id": A, "ligacao": "x" * 2000})[0], 400
        )

    def test_sem_o_painel_ligado_e_503(self) -> None:
        for rota, corpo in ((painel.ROTA_DOS_ITENS, {"tenant_id": A}), (painel.ROTA_DA_DESCARGA, {"tenant_id": A, "ligacao": "a.b"})):
            self.assertEqual(_pedir(_app(None), rota, corpo), (503, {"outcome": "painel_por_ligar"}))

    def test_nenhum_texto_de_rede_nem_botao_de_publicar_na_resposta(self) -> None:
        mundo = Mundo()
        mundo.arte(A)
        _estado, corpo = _pedir(_app(mundo), painel.ROTA_DOS_ITENS, {"tenant_id": A})
        self.assertEqual(set(corpo["itens"][0]), {"referencia", "estado", "tema", "legenda", "nota", "imagem", "ligacao"})


#: O STO do AGR, com o endpoint **interno** do perfil `sto-proprio`.
STO_INTERNO = {
    "KAMBA_STORAGE_ENDPOINT": "http://seaweedfs:8333",
    "KAMBA_STORAGE_BUCKET": "kamba-teste",
    "KAMBA_STORAGE_REGION": "af-south-1",
    "KAMBA_STORAGE_DESTINO_COUNTRY": "AO",
    "KAMBA_STORAGE_DESTINO_PROVIDER": "seaweedfs",
}
PUBLICO = "https://sto.exemplo.invalid"


class _Cofre:
    def get(self, ref: str) -> str:
        return {"storage_access_key_id": "AKIAENSAIO", "storage_secret_access_key": "segredo-de-ensaio"}[ref]


class TestOEndpointPublico(unittest.TestCase):
    """A decisao do fundador de 2026-11-23 (A): os URLs que o navegador abre
    assinam-se com o endpoint publico do STO, nunca com o interno."""

    def _assinador(self, ambiente: str, publico: str | None, interno: Any = None) -> Any:
        from kamba_core.storage import ler_config  # noqa: PLC0415

        env = dict(STO_INTERNO) if publico is None else {**STO_INTERNO, painel.VAR_ENDPOINT_PUBLICO: publico}
        return painel.assinador_publico(
            armazenamento=interno if interno is not None else object(),
            config=ler_config(ambiente=ambiente, env=STO_INTERNO),
            segredos=_Cofre(),
            ambiente=ambiente,
            env=env,
        )

    def test_o_url_assinado_usa_o_endpoint_publico_e_nunca_o_interno(self) -> None:
        assinador = self._assinador("prod", PUBLICO)
        mundo = Mundo()
        item = mundo.arte(A)
        mundo.painel = painel.PainelDoSocial(
            itens=lambda tenant: tuple(mundo.itens.get(tenant, [])),
            assinador=assinador,
            chaves=lambda: [CHAVE],
            relogio=lambda: AGORA,
        )
        estado, corpo = _pedir(_app(mundo), painel.ROTA_DOS_ITENS, {"tenant_id": A})
        self.assertEqual(estado, 200)
        ligacao = ligacao_assinada(CHAVE, A, item.arte_ref or "", AGORA)
        estado, aberta = _pedir(_app(mundo), painel.ROTA_DA_DESCARGA, {"tenant_id": A, "ligacao": ligacao})
        self.assertEqual(estado, 200)
        for url in (corpo["itens"][0]["imagem"], aberta["url"]):
            self.assertTrue(url.startswith(f"{PUBLICO}/"), url)
            self.assertNotIn("seaweedfs", url)
            self.assertIn("X-Amz-Expires=300", url)

    def test_sem_endpoint_publico_fora_de_dev_e_503_e_nao_cai_para_o_interno(self) -> None:
        interno = Mundo().storage
        for ambiente in ("staging", "prod"):
            for publico in (None, "", "sto sem forma", "https://utilizador:senha@sto.exemplo.invalid"):
                self.assertIsNone(self._assinador(ambiente, publico, interno), (ambiente, publico))
        mundo = Mundo()
        mundo.arte(A)
        mundo.painel = painel.PainelDoSocial(
            itens=lambda tenant: tuple(mundo.itens.get(tenant, [])), assinador=None, chaves=lambda: [CHAVE]
        )
        for rota, corpo in (
            (painel.ROTA_DOS_ITENS, {"tenant_id": A}),
            (painel.ROTA_DA_DESCARGA, {"tenant_id": A, "ligacao": "a.b"}),
        ):
            self.assertEqual(_pedir(_app(mundo), rota, corpo), (503, {"outcome": "painel_por_ligar"}))

    def test_um_endpoint_http_e_recusado_fora_de_dev_e_passa_em_dev(self) -> None:
        for ambiente in ("staging", "prod"):
            self.assertIsNone(self._assinador(ambiente, "http://sto.exemplo.invalid"), ambiente)
        assinador = self._assinador("dev", "http://localhost:8333")
        url = assinador.sign_url(Ctx(A), ObjectRef(f"t/{A}/arte/2026/11/0b1c2d3e-4f50-4617-8a9b-0c1d2e3f4a51", 0), ttl_seconds=300)
        self.assertTrue(url.startswith("http://localhost:8333/"), url)
        # Em `dev`, sem endpoint publico, assina-se com o do AGR.
        interno = Mundo().storage
        self.assertIs(self._assinador("dev", None, interno), interno)


class TestAMontagem(unittest.TestCase):
    def test_o_arranque_liga_as_rotas_a_credencial_do_painel_e_nao_a_do_shim(self) -> None:
        """A premissa corrigida da Q2 = A: quem tem o `agr_internal_token` corre o
        `/internal/turn` de qualquer tenant, e o painel nao o tem."""
        import pathlib

        fonte = (pathlib.Path(__file__).resolve().parents[1] / "src/kamba_agr/__main__.py").read_text(encoding="utf-8")
        inicio = fonte.index("*painel_social.rotas(")
        bloco = fonte[inicio : fonte.index("painel=", inicio)]
        self.assertIn("segredos.get(SEGREDO_DO_PAINEL)", bloco)
        self.assertNotIn("SEGREDO_DA_API", bloco)


if __name__ == "__main__":
    unittest.main()
