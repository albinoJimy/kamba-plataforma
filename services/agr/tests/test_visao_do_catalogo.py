"""A visao do catalogo do dono pelo gateway (KAM-231, criterio 2; decisao P2 A).

O `ClienteDeLlm.ver` e o unico caminho de uma foto ao modelo: so o papel
`vision`, so uma `ImagemLimpa`, instrucao fixa, o *gate* antes de qualquer
octeto, e uma linha em `dat.llm_call_log` por chamada. **So imagens
sinteticas**, desenhadas aqui pelo Pillow; nenhuma chave real.
"""

from __future__ import annotations

import ast
import base64
import io
import pathlib
import unittest
from decimal import Decimal
from typing import Any

from PIL import Image
from test_llm_cliente import PRECOS, REAIS, _Ligacao, _resposta, _Transporte

from kamba_agr import metricas as metricas_mod
from kamba_agr.catalogo.visao import VisaoPeloGateway
from kamba_agr.llm import aliases as aliases_mod
from kamba_agr.llm import destinos as destinos_mod
from kamba_agr.llm.cliente import INSTRUCAO_DA_VISAO, PAPEL_DA_VISAO, ClienteDeLlm, ContextoDeChamada
from kamba_agr.llm.erros import RESULTADO_DESTINO, RESULTADO_OK, DestinoNegado
from kamba_core.catalogo.exif import ImagemComMetadados, ImagemLimpa, limpar_metadados, tem_metadados
from kamba_core.catalogo.pipeline import ErroDaVisao, ExtractorDeVisao

TENANT = "11111111-1111-4111-8111-111111111111"
CTX = ContextoDeChamada(tenant_id=TENANT, trace_id="0af7651916cd43dd8448eb211c80319c")
SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "kamba_agr"

ALIAS_VISAO = aliases_mod.Alias(
    nome="kamba-vision",
    papel="vision",
    timeout=20,
    fornecedores=("anthropic",),
    modelos=("claude-haiku-5-5",),
    max_tokens=REAIS["vision"].max_tokens,
)
ALIAS_CHAT = aliases_mod.Alias(
    nome="kamba-chat", papel="chat", timeout=20, fornecedores=("anthropic",), modelos=("claude-haiku-5-5",)
)


def _jpeg_com_gps() -> bytes:
    exif = Image.Exif()
    exif[0x010F] = "Fabricante 999"
    exif[0x8825] = {1: "S", 2: (8.0, 50.0, 0.0)}
    saida = io.BytesIO()
    Image.new("RGB", (64, 48), (200, 40, 40)).save(saida, format="JPEG", exif=exif)
    return saida.getvalue()


def _cliente(
    transporte: _Transporte | None = None, ambiente: str = destinos_mod.AMBIENTE_STAGING
) -> tuple[ClienteDeLlm, _Ligacao, _Transporte, metricas_mod.MetricasDoAgr]:
    lig = _Ligacao()
    t = transporte or _Transporte()
    met = metricas_mod.MetricasDoAgr()
    cliente = ClienteDeLlm(
        aliases={"vision": ALIAS_VISAO, "chat": ALIAS_CHAT},
        tabela_de_precos=PRECOS,
        porta_de_destinos=destinos_mod.arrancar(ambiente),
        abrir_ligacao=lambda: lig,
        chave_virtual=lambda tenant: f"sk-virtual-{tenant}",
        url_do_proxy="http://litellm:4000",
        metricas=met,
        transporte=t,
    )
    return cliente, lig, t, met


class TestAImagemLimpa(unittest.TestCase):
    def test_nasce_do_limpar_metadados(self) -> None:
        bruto = _jpeg_com_gps()
        self.assertTrue(tem_metadados(bruto))
        limpa = ImagemLimpa.de(bruto)
        self.assertFalse(tem_metadados(limpa.corpo))
        self.assertEqual(limpa.content_type, "image/jpeg")

    def test_bytes_com_metadados_nao_fazem_uma(self) -> None:
        for corpo in (_jpeg_com_gps(), b"", b"texto", "nao-bytes"):
            with self.subTest(corpo=str(corpo)[:10]):
                with self.assertRaises(ImagemComMetadados):
                    ImagemLimpa(corpo)  # type: ignore[arg-type]

    def test_limpar_duas_vezes_da_os_mesmos_bytes(self) -> None:
        uma = limpar_metadados(_jpeg_com_gps())
        self.assertEqual(limpar_metadados(uma), uma)


class TestOVer(unittest.TestCase):
    def test_o_corpo_leva_a_instrucao_fixa_e_a_imagem_limpa(self) -> None:
        cliente, lig, t, _ = _cliente()
        resposta = cliente.ver(ImagemLimpa.de(_jpeg_com_gps()), CTX)
        self.assertEqual(resposta.resultado, RESULTADO_OK)
        url, cabecalhos, corpo, _tecto = t.chamadas[0]
        self.assertTrue(url.endswith("/chat/completions"))
        self.assertEqual(corpo["model"], "kamba-vision")
        self.assertEqual(corpo["max_tokens"], REAIS["vision"].max_tokens)
        sistema, utilizador = corpo["messages"]
        self.assertEqual(sistema, {"role": "system", "content": INSTRUCAO_DA_VISAO})
        (parte,) = utilizador["content"]
        prefixo = "data:image/jpeg;base64,"
        self.assertTrue(parte["image_url"]["url"].startswith(prefixo))
        enviados = base64.b64decode(parte["image_url"]["url"][len(prefixo) :])
        self.assertFalse(tem_metadados(enviados))
        self.assertNotIn(b"Fabricante", enviados)
        self.assertEqual(cabecalhos["Authorization"], f"Bearer sk-virtual-{TENANT}")
        # Uma linha, com o papel e o custo.
        (linha,) = lig.linhas()
        self.assertEqual(linha["papel"], PAPEL_DA_VISAO)
        self.assertEqual(linha["tenant_id"], TENANT)
        self.assertIsNotNone(linha["custo_usd"])

    def test_so_aceita_uma_imagem_limpa(self) -> None:
        cliente, lig, t, _ = _cliente()
        forjada = object.__new__(ImagemLimpa)
        object.__setattr__(forjada, "corpo", _jpeg_com_gps())
        for imagem in (_jpeg_com_gps(), forjada, None):
            with self.subTest(imagem=type(imagem).__name__):
                with self.assertRaises(TypeError):
                    cliente.ver(imagem, CTX)  # type: ignore[arg-type]
        self.assertEqual(t.chamadas, [])
        self.assertEqual(lig.linhas(), [])

    def test_uma_subclasse_que_troca_os_bytes_nao_passa(self) -> None:
        """Achado 7 da revisao: o `corpo` como propriedade dava bytes diferentes a cada leitura."""
        limpa = ImagemLimpa.de(_jpeg_com_gps())
        suja = _jpeg_com_gps()

        class Troca(ImagemLimpa):
            leituras = 0

            def __getattribute__(self, nome: str):  # type: ignore[no-untyped-def]
                if nome == "corpo":
                    Troca.leituras += 1
                    return limpa.corpo if Troca.leituras < 3 else suja
                return super().__getattribute__(nome)

        cliente, lig, t, _ = _cliente()
        with self.assertRaises(TypeError):
            cliente.ver(Troca(limpa.corpo), CTX)
        self.assertEqual(t.chamadas, [])
        self.assertEqual(lig.linhas(), [])

    def test_em_prod_sem_destino_nada_sai_e_fica_a_linha(self) -> None:
        cliente, lig, t, _ = _cliente(ambiente=destinos_mod.AMBIENTE_PROD)
        with self.assertRaises(DestinoNegado):
            cliente.ver(ImagemLimpa.de(_jpeg_com_gps()), CTX)
        self.assertEqual(t.chamadas, [])
        self.assertEqual(lig.linhas()[0]["resultado"], RESULTADO_DESTINO)

    def test_a_finalidade_e_a_da_visao(self) -> None:
        vistas: list[tuple[str, str, str]] = []

        class Porta:
            def autorizar(self, tenant: str, fornecedor: str, finalidade: str) -> None:
                vistas.append((tenant, fornecedor, finalidade))

        cliente, _, _, _ = _cliente()
        cliente._destinos = Porta()  # type: ignore[assignment]
        cliente.ver(ImagemLimpa.de(_jpeg_com_gps()), CTX)
        self.assertEqual(vistas, [(TENANT, "anthropic", destinos_mod.finalidade_de("vision"))])

    def test_sem_o_papel_vision_levanta(self) -> None:
        cliente, _, t, _ = _cliente()
        cliente._aliases = {"chat": ALIAS_CHAT}  # type: ignore[assignment]
        with self.assertRaises(Exception):
            cliente.ver(ImagemLimpa.de(_jpeg_com_gps()), CTX)
        self.assertEqual(t.chamadas, [])


class TestOAdaptador(unittest.TestCase):
    def test_e_o_extractor_do_kam_049(self) -> None:
        cliente, _, _, _ = _cliente()
        visao = VisaoPeloGateway(cliente)
        self.assertIsInstance(visao, ExtractorDeVisao)
        self.assertEqual(visao.fornecedores, ("anthropic",))

    def test_limpa_outra_vez_e_devolve_o_texto_e_o_custo(self) -> None:
        texto = '{"nome": {"valor": "Sumo", "confianca": 0.9}}'
        corpo: dict[str, Any] = _resposta()
        corpo["choices"] = [{"message": {"content": texto}}]
        cliente, lig, t, _ = _cliente(_Transporte((200, corpo, {})))
        resposta = VisaoPeloGateway(cliente).extrair(TENANT, _jpeg_com_gps())
        self.assertEqual(resposta.texto, texto)
        self.assertEqual(resposta.custo_usd, lig.linhas()[0]["custo_usd"])
        self.assertGreater(resposta.custo_usd, Decimal(0))
        enviado = t.chamadas[0][2]["messages"][1]["content"][0]["image_url"]["url"]
        self.assertNotIn(b"Fabricante", base64.b64decode(enviado.split(",", 1)[1]))

    def test_uma_falha_vira_erro_da_visao(self) -> None:
        cliente, lig, _, _ = _cliente(ambiente=destinos_mod.AMBIENTE_PROD)
        with self.assertRaises(ErroDaVisao) as caso:
            VisaoPeloGateway(cliente).extrair(TENANT, _jpeg_com_gps())
        self.assertEqual(caso.exception.custo_usd, Decimal(0))
        self.assertEqual(len(lig.linhas()), 1)

    def test_bytes_que_nao_sao_imagem_nao_saem(self) -> None:
        cliente, lig, t, _ = _cliente()
        with self.assertRaises(ErroDaVisao):
            VisaoPeloGateway(cliente).extrair(TENANT, b"GIF89a e mais nada")
        self.assertEqual(t.chamadas, [])
        self.assertEqual(lig.linhas(), [])


class TestQuemChamaOVer(unittest.TestCase):
    """O `ver` so se chama de `catalogo/visao.py`, como o `embeber` so do `tls/embeddings.py`."""

    def test_so_o_adaptador_do_catalogo(self) -> None:
        quem: list[str] = []
        for ficheiro in SRC.rglob("*.py"):
            arvore = ast.parse(ficheiro.read_text(encoding="utf-8"))
            for no in ast.walk(arvore):
                if isinstance(no, ast.Attribute) and no.attr == "ver" and isinstance(no.ctx, ast.Load):
                    quem.append(ficheiro.relative_to(SRC).as_posix())
        self.assertEqual(sorted(set(quem)), ["catalogo/visao.py"])


if __name__ == "__main__":
    unittest.main()
