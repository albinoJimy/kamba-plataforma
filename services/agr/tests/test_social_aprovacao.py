"""KAM-122: a arte, a aprovacao e a entrega do modulo social.

* o desenho em JPEG (`social/desenho.py`): os dois formatos, sem EXIF, as marcas
  de IA de um fundo gerado preservadas, e o texto que nao cabe recusado;
* o fundo gerado (`social/fundos.py`): o destino autorizado, o OCR, as duas
  regeracoes, e **0 artes finais com texto gerado** em cem fundos adversariais;
* o `hash` da aprovacao e a `ref` da accao (`social/aprovacao.py`);
* as cinco tools pela ToolLayer real: renderizar duas vezes, pedir duas vezes,
  aprovar duas vezes, entregar duas vezes, a edicao depois da aprovacao, a
  legenda do dono pelas barreiras, as tres tentativas e o alerta de custo;
* o grafo do dono, do botao Arte a entrega.

O SQL do repositorio e o gatilho da `0085` correm contra o PostgreSQL no gate 8.
"""

from __future__ import annotations

import asyncio
import datetime
import io
import re
import shutil
import struct
import unittest
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

from kamba_core.offboarding.exportacao import LigacaoRecusada, abrir_ligacao, ligacao_assinada
from kamba_core.storage.fake import criar_storage_fake
from PIL import Image, ImageDraw, ImageFont

from kamba_agr.social import aprovacao, arte, desenho, fundos, ocr, regras
from kamba_agr.social.repositorio import (
    APROVADO,
    ENTREGUE,
    PENDENTE_APROVACAO,
    REJEITADO,
    TRANSICOES,
    ItemNovo,
)
from kamba_agr.tls import catalogo as catalogo_mod
from kamba_agr.tls import social_tools
from kamba_agr.tls.camada import ToolLayer
from kamba_agr.tls.especificacoes import Catalogo
from kamba_agr.social.politicas import Alegacoes, Lexico
from test_social_dono import A, AGORA, B, CONTACTO, POLITICAS, Mundo, _perfil_completo

RAIZ = Path(__file__).resolve().parents[3]
REVISAO = RAIZ / "db" / "migrations" / "versions" / "0085_arte_e_aprovacao_do_social.py"

PROMOCAO = regras.Facto("Desconto de 5.000 Kz em vestidos ate 30/11", promocao=True, valido_ate=datetime.date(2026, 11, 30))
PRECO = regras.Facto("Vestido de capulana a 12.500 Kz")
TELEFONE = regras.Facto("Encomendas pelo 999 123 456")


def _fonte_de_ensaio(_papel: str, tamanho: int) -> Any:
    """A fonte por omissao do Pillow, para correr sem a Noto (que vive na imagem do AGR)."""
    return ImageFont.load_default(size=tamanho)


RENDERIZADOR = desenho.RenderizadorPillow(carregar_fonte=_fonte_de_ensaio)


def _segmentos(jpeg: bytes) -> list[tuple[int, bytes]]:
    return desenho._segmentos_antes_da_imagem(jpeg)


def _cena(texto: str | None = None, *, c2pa: bool = False, xmp: bool = False, exif: bool = False) -> bytes:
    """Uma cena JPEG de ensaio; com `texto`, letras desenhadas nela."""
    imagem = Image.new("RGB", (640, 640), (200, 180, 150))
    if texto:
        ImageDraw.Draw(imagem).text((40, 300), texto, font=ImageFont.load_default(size=72), fill=(0, 0, 0))
    saida = io.BytesIO()
    imagem.save(saida, "JPEG", quality=85)
    corpo = saida.getvalue()
    extra = b""
    if c2pa:
        extra += desenho._segmento(0xEB, b"JP" + b"\x00\x01" + b"jumb-c2pa-manifesto")
    if xmp:
        extra += desenho._segmento(0xE1, desenho._XMP_NS + b"<x:xmpmeta>gerado</x:xmpmeta>")
    if exif:
        extra += desenho._segmento(0xE1, b"Exif\x00\x00" + b"II*\x00GPS-de-ensaio")
    return corpo[:2] + extra + corpo[2:]


def _composicao(formato: str = "quadrado", template: str = "produtos_faixa") -> arte.Composicao:
    perfil = _perfil_completo(factos=(PRECO, TELEFONE))
    dados = arte.dados_da_arte(perfil, "produto", datetime.date(2026, 11, 25))
    return arte.compor(dados, arte.TEMPLATES[template], formato)


# ====================================================================== o desenho


class TestDesenho(unittest.TestCase):
    def test_os_dois_formatos_em_jpeg_sem_exif(self) -> None:
        for formato, dimensoes in arte.FORMATOS.items():
            with self.subTest(formato=formato):
                jpeg = RENDERIZADOR.desenhar(_composicao(formato), ("#FFAA00",))
                self.assertEqual(jpeg[:2], b"\xff\xd8")
                imagem = Image.open(io.BytesIO(jpeg))
                self.assertEqual(imagem.format, "JPEG")
                self.assertEqual(imagem.size, dimensoes)
                self.assertFalse(imagem.getexif())
                self.assertFalse(any(m == 0xE1 for m, _ in _segmentos(jpeg)))

    def test_renderizar_duas_vezes_da_os_mesmos_bytes(self) -> None:
        composicao = _composicao()
        self.assertEqual(RENDERIZADOR.desenhar(composicao, ("#FFAA00",)), RENDERIZADOR.desenhar(composicao, ("#FFAA00",)))

    def test_cada_template_desenha_nos_dois_formatos(self) -> None:
        perfil = _perfil_completo(factos=(PRECO, TELEFONE))
        dados = arte.dados_da_arte(perfil, "produto", datetime.date(2026, 11, 25))
        for template in arte.TEMPLATES.values():
            for formato in arte.FORMATOS:
                with self.subTest(template=template.template_id, formato=formato):
                    jpeg = RENDERIZADOR.desenhar(arte.compor(dados, template, formato), ())
                    self.assertEqual(Image.open(io.BytesIO(jpeg)).size, arte.FORMATOS[formato])

    def test_texto_que_nao_cabe_recusa_e_nao_corta(self) -> None:
        enorme = arte.Composicao(arte.TEMPLATES["produtos_faixa"], "quadrado", (arte.Linha("preco", "9" * 90 + " Kz"),))
        with self.assertRaises(arte.Recusa) as erro:
            RENDERIZADOR.desenhar(enorme, ())
        self.assertEqual(erro.exception.motivo, "texto_nao_cabe")

    def test_sem_a_noto_a_arte_nao_se_desenha(self) -> None:
        with self.assertRaises(desenho.FontesEmFaltaError):
            desenho.Fontes.do_sistema(Path("/nao/existe"))

    def test_as_marcas_de_ia_da_cena_ficam_e_o_exif_sai(self) -> None:
        cena = _cena(c2pa=True, xmp=True, exif=True)
        jpeg = RENDERIZADOR.desenhar(_composicao(), (), cena)
        segmentos = _segmentos(jpeg)
        self.assertTrue(any(m == 0xEB and c.startswith(b"JP") for m, c in segmentos), "C2PA")
        self.assertTrue(any(m == 0xE1 and c.startswith(desenho._XMP_NS) and b"gerado" in c for m, c in segmentos))
        self.assertFalse(any(m == 0xE1 and c.startswith(b"Exif") for m, c in segmentos), "EXIF")
        self.assertFalse(Image.open(io.BytesIO(jpeg)).getexif())

    def test_uma_cena_sem_xmp_leva_o_tipo_de_fonte_digital_do_iptc(self) -> None:
        jpeg = RENDERIZADOR.desenhar(_composicao(), (), _cena())
        xmp = [c for m, c in _segmentos(jpeg) if m == 0xE1 and c.startswith(desenho._XMP_NS)]
        self.assertEqual(len(xmp), 1)
        self.assertIn(desenho.TIPO_DE_FONTE_DIGITAL.encode(), xmp[0])

    def test_o_fundo_do_template_nao_leva_marca_de_ia(self) -> None:
        jpeg = RENDERIZADOR.desenhar(_composicao(), ("#FFAA00",))
        self.assertFalse(desenho.marcas_de_ia(jpeg))


# ====================================================================== o OCR e o fundo


class OcrDuplo:
    """Le o «texto» de uma cena de ensaio pela marca que o gerador duplo lhe pos."""

    def __init__(self, *, falha: bool = False) -> None:
        self.falha = falha
        self.lidas = 0

    def tem_texto(self, imagem: bytes) -> bool:
        self.lidas += 1
        if self.falha:
            raise ocr.OcrIndisponivelError("em baixo")
        return b"COM-TEXTO" in imagem


class GeradorDeFundosDuplo:
    nome = "gerador-de-fundos-duplo"

    def __init__(self, *com_texto: bool, custo: str = "0.0336") -> None:
        self.com_texto = list(com_texto) or [False]
        self.pedidos: list[fundos.PedidoDeFundo] = []
        self.custo = Decimal(custo)

    def gerar(self, pedido: fundos.PedidoDeFundo) -> fundos.Fundo:
        self.pedidos.append(pedido)
        texto = self.com_texto[min(len(self.pedidos), len(self.com_texto)) - 1]
        return fundos.Fundo(_cena() + (b"COM-TEXTO" if texto else b""), self.custo)


class DestinosDuplos:
    def __init__(self, autorizado: bool = True) -> None:
        self.autorizado = autorizado
        self.pedidos: list[tuple[str, str, str]] = []

    def autorizar(self, tenant_id: str, fornecedor: str, finalidade: str) -> None:
        self.pedidos.append((tenant_id, fornecedor, finalidade))
        if not self.autorizado:
            raise PermissionError("sem apd_ref")


PEDIDO = fundos.PedidoDeFundo("produtos", "quadrado")


class TestFundo(unittest.TestCase):
    def test_sem_gerador_ligado_nada_sai_e_a_arte_usa_o_template(self) -> None:
        destinos = DestinosDuplos()
        escolha = fundos.escolher_fundo(A, PEDIDO, fundos.GeradorPorLigar(), OcrDuplo(), destinos)
        self.assertEqual((escolha.imagem, escolha.fundo, escolha.motivo, escolha.pedidos), (None, "gradiente", "por_ligar", 0))
        self.assertEqual(destinos.pedidos, [])

    def test_sem_destino_autorizado_nenhum_pedido_sai(self) -> None:
        gerador = GeradorDeFundosDuplo()
        destinos = DestinosDuplos(autorizado=False)
        escolha = fundos.escolher_fundo(A, PEDIDO, gerador, OcrDuplo(), destinos)
        self.assertEqual((escolha.fundo, escolha.motivo), ("gradiente", "sem_destino"))
        self.assertEqual(gerador.pedidos, [])
        self.assertEqual(destinos.pedidos, [(A, gerador.nome, "geracao_de_imagem")])

    def test_regera_ate_duas_vezes_e_depois_cai_no_template(self) -> None:
        gerador = GeradorDeFundosDuplo(True, True, False)
        escolha = fundos.escolher_fundo(A, PEDIDO, gerador, OcrDuplo(), DestinosDuplos())
        self.assertEqual((escolha.fundo, escolha.pedidos), ("gerado", 3))
        self.assertEqual(escolha.custo_usd, Decimal("0.1008"))
        gerador = GeradorDeFundosDuplo(True, True, True, False)
        escolha = fundos.escolher_fundo(A, PEDIDO, gerador, OcrDuplo(), DestinosDuplos())
        self.assertEqual((escolha.imagem, escolha.fundo, escolha.motivo), (None, "gradiente", "com_texto"))
        self.assertEqual(len(gerador.pedidos), 3)

    def test_o_ocr_em_baixo_e_texto(self) -> None:
        escolha = fundos.escolher_fundo(A, PEDIDO, GeradorDeFundosDuplo(False), OcrDuplo(falha=True), DestinosDuplos())
        self.assertEqual((escolha.imagem, escolha.motivo), (None, "com_texto"))

    def test_cem_fundos_adversariais_zero_artes_com_texto_gerado(self) -> None:
        # Criterio 3: em cem fundos, os que trazem texto nunca chegam a arte.
        finais_com_texto = 0
        for i in range(100):
            sequencia = [(i * 7 + k) % 3 != 0 for k in range(3)]
            escolha = fundos.escolher_fundo(A, PEDIDO, GeradorDeFundosDuplo(*sequencia), OcrDuplo(), DestinosDuplos())
            jpeg = RENDERIZADOR.desenhar(_composicao(), (), escolha.imagem)
            if escolha.imagem is not None and b"COM-TEXTO" in escolha.imagem:
                finais_com_texto += 1
            self.assertNotIn(b"COM-TEXTO", jpeg)
        self.assertEqual(finais_com_texto, 0)

    def test_o_pedido_ao_fornecedor_nao_leva_dados_do_tenant(self) -> None:
        for tipo in arte.TIPOS_DE_NEGOCIO:
            for formato in arte.FORMATOS:
                texto = fundos.descricao_do_fundo(tipo, formato)
                self.assertFalse(re.search(r"\d", texto), texto)
                self.assertIn("sem texto", texto)
                for proibido in ("Loja", "Ana", "roupa"):
                    self.assertNotIn(proibido, texto)

    def test_a_leitura_do_ocr(self) -> None:
        self.assertFalse(ocr.ha_texto_em(""))
        self.assertFalse(ocr.ha_texto_em(" | . ~ \n"))
        self.assertFalse(ocr.ha_texto_em("a b c"))
        self.assertTrue(ocr.ha_texto_em("SALDOS"))
        self.assertTrue(ocr.ha_texto_em("12 500"))

    def test_o_tesseract_em_falta_levanta(self) -> None:
        with self.assertRaises(ocr.OcrIndisponivelError):
            ocr.TesseractOcr(binario="tesseract-que-nao-existe-kam122").tem_texto(_cena())

    @unittest.skipUnless(shutil.which("tesseract"), "o tesseract vive na imagem do AGR")
    def test_o_tesseract_le_texto_e_nao_le_uma_cena_lisa(self) -> None:
        leitor = ocr.TesseractOcr()
        self.assertTrue(leitor.tem_texto(_cena("SALDOS HOJE")))
        self.assertFalse(leitor.tem_texto(_cena()))
        # A arte do template tem o texto do codigo: o OCR le-o (e por isso so
        # corre sobre o fundo, antes do texto).
        self.assertTrue(leitor.tem_texto(RENDERIZADOR.desenhar(_composicao(), ("#1F3A5F",))))


# ====================================================================== o hash e a ref


class TestAprovacao(unittest.TestCase):
    def test_o_hash_muda_com_cada_parte(self) -> None:
        base = aprovacao.hash_da_aprovacao("Legenda", "a" * 64, 3)
        self.assertRegex(base, r"^[0-9a-f]{64}$")
        self.assertEqual(base, aprovacao.hash_da_aprovacao("Legenda", "a" * 64, 3))
        for outro in (
            aprovacao.hash_da_aprovacao("Legenda.", "a" * 64, 3),
            aprovacao.hash_da_aprovacao("Legenda", "b" * 64, 3),
            aprovacao.hash_da_aprovacao("Legenda", "a" * 64, 4),
        ):
            self.assertNotEqual(base, outro)

    def test_a_ref_vai_e_volta_e_nao_se_confunde_com_a_do_catalogo(self) -> None:
        item = str(uuid.uuid4())
        hash_ = "c" * 64
        self.assertEqual(aprovacao.ler_ref(aprovacao.ref_da_accao(item, hash_)), (item, hash_, False))
        self.assertEqual(aprovacao.ler_ref(aprovacao.ref_da_accao(item, hash_, 2)), (item, hash_, False))
        self.assertEqual(
            aprovacao.ler_ref(aprovacao.ref_da_accao(item, hash_, 3, reforcada=True)), (item, hash_, True)
        )
        from kamba_agr.tls.catalogo_tools import _ler_ref as ref_do_catalogo

        self.assertIsNone(ref_do_catalogo(aprovacao.ref_da_accao(item, hash_)))
        self.assertIsNone(aprovacao.ler_ref(f"{item}:{'d' * 16}"))

    def test_as_transicoes_sao_as_do_gatilho_da_revisao(self) -> None:
        texto = REVISAO.read_text(encoding="utf-8")
        bloco = texto.split("TRANSICOES_SQL = ", 1)[1].split('"""', 2)[1]
        lidas = set()
        for de, paras in re.findall(r"OLD\.estado = '(\w+)' AND NEW\.estado IN \(([^)]*)\)", bloco):
            lidas |= {(de, p) for p in re.findall(r"'(\w+)'", paras)}
        self.assertEqual(lidas, set(TRANSICOES))


# ====================================================================== as tools


class AccoesDuplas:
    """A `owner_actions` em memoria: `propor` com a `UNIQUE (tenant_id, tipo, ref)`."""

    def __init__(self) -> None:
        self.linhas: dict[str, dict[str, Any]] = {}

    def propor(self, _ligacao: Any, tenant: str, contacto: str, tipo: str, ref: str, instante: datetime.datetime) -> str:
        for action_id, linha in self.linhas.items():
            if (linha["tenant"], linha["tipo"], linha["ref"]) == (tenant, tipo, ref):
                return action_id
        action_id = str(uuid.uuid4())
        self.linhas[action_id] = {
            "tenant": tenant,
            "tipo": tipo,
            "ref": ref,
            "estado": "pendente",
            "contacto": contacto.lower(),
            "confirmada_at": None,
            "expira_at": instante + datetime.timedelta(minutes=15),
        }
        return action_id

    def ler(self, _ligacao: Any, tenant: str, action_id: str) -> Any:
        linha = self.linhas.get(action_id)
        if linha is None or linha["tenant"] != tenant:
            return None
        return linha["tipo"], linha["ref"], linha["estado"], linha["contacto"], linha["confirmada_at"], linha["expira_at"]

    def confirmar(self, action_id: str) -> None:
        self.linhas[action_id].update(estado="confirmada", confirmada_at=AGORA)


class MundoDaArte(Mundo):
    """O `Mundo` do KAM-121 com as portas da arte em duplo."""

    def __init__(self, *, gerador_de_fundos: Any = None, destinos: Any = None, limite_de_imagens: int | None = 20, **kw: Any) -> None:
        super().__init__(**kw)
        self.repo.limite_de_imagens = limite_de_imagens
        self.accoes = AccoesDuplas()
        self.storage = criar_storage_fake(lambda: AGORA).storage
        self.gerador_de_fundos = gerador_de_fundos or fundos.GeradorPorLigar()
        portas = social_tools.PortasDoSocial(
            repositorio=lambda _ligacao: self.repo,
            screening=self.screening,
            gerador=self.gerador,
            lexico=lambda: Lexico.carregar(POLITICAS),
            alegacoes=lambda: Alegacoes.carregar(POLITICAS),
            renderizador=RENDERIZADOR,
            fundos=self.gerador_de_fundos,
            ocr=OcrDuplo(),
            destinos=destinos or DestinosDuplos(),
            storage=self.storage,
            propor=self.accoes.propor,
            ler_accao=self.accoes.ler,
        )
        do_catalogo = catalogo_mod.catalogo_do_piloto(social_tools.executores(portas, lambda: AGORA))
        especificacoes = (self.camada.catalogo["get_store_info"], *(do_catalogo[n] for n in social_tools.MODELOS))
        self.camada = ToolLayer(Catalogo(especificacoes), abrir_ligacao=self.ligacao.nova_vaga)

    def item_com_legenda(self, tenant: str = A, *, tipo: str = "produto", legenda: str = "Vestidos novos para a semana.") -> str:
        perfil = self.com_perfil(tenant, factos=(PRECO, TELEFONE, PROMOCAO))
        del perfil
        content_item_id = str(uuid.uuid4())
        calendar_id = str(uuid.uuid4())
        # Uma semana por item: o `abrir` da mesma semana devolvia o calendario activo.
        semana = f"2026-W{48 + sum(1 for c in self.repo.calendarios.values() if c.tenant_id == tenant)}"
        self.repo.abrir(
            tenant,
            semana,
            calendar_id,
            1,
            "permitida",
            "1.0.0",
            [ItemNovo(content_item_id, tipo, "Tema", datetime.datetime(2026, 11, 25, 11, tzinfo=datetime.UTC), False, "1.0.0")],
        )
        item = self.repo.itens[content_item_id]
        self.repo.gravar_legenda(item, legenda, False, "1.0.0")
        return regras.referencia_do_item(content_item_id)

    def aprovar(self, action_id: str, *, tenant: str = A) -> Any:
        """O `approve_content` com a `Confirmation` do botao, como o no `confirm` o chama."""
        from kamba_agr.tls.contexto import Confirmation

        ctx = self.ctx(tenant)
        return asyncio.run(
            self.camada.invoke(
                ctx,
                "approve_content",
                {"action_id": action_id},
                allowed=tuple(social_tools.MODELOS),
                confirmation=Confirmation(botao=f"confirm:{action_id}", contact_id=CONTACTO, turn_id=ctx.turn_id),
                idempotency_key=f"approve_content:{action_id}:{uuid.uuid4().hex}",
            )
        )


def com_corrida(repo: Any) -> list[Any]:
    """KAM-256: outra entrega do mesmo item grava entre a leitura e a escrita desta.

    O item foi lido `aprovado`. No primeiro `entregar`, a outra entrega corre com
    a mesma leitura e ganha; a desta, com a versao lida, levanta `ItemMudouError`
    pela guarda do repositorio, e a releitura encontra o item `entregue`. A
    corrida e a ordem das duas chamadas, sem a base. Devolve os itens que cada
    `entregar` gravou, para contar as entregas.
    """
    original = repo.entregar
    gravadas: list[Any] = []

    def contado(item: Any, instante: datetime.datetime) -> tuple[Any, bool]:
        gravado = original(item, instante)
        gravadas.append(gravado[0])
        return gravado

    def corrida(item: Any, instante: datetime.datetime) -> tuple[Any, bool]:
        repo.entregar = contado
        contado(item, instante)
        return contado(item, instante)

    repo.entregar = corrida
    return gravadas


class TestAsTools(unittest.TestCase):
    def setUp(self) -> None:
        self.mundo = MundoDaArte()
        self.ref = self.mundo.item_com_legenda()

    def _item(self) -> Any:
        prefixo = regras.prefixo_da_referencia(self.ref)
        (item,) = self.mundo.repo.itens_por_prefixo(A, prefixo)
        return item

    def test_a_arte_vai_ao_sto_do_tenant_com_o_texto_dos_factos(self) -> None:
        r = self.mundo.invocar("generate_art", {"referencia": self.ref})
        self.assertTrue(r.ok, r.error)
        self.assertEqual(r.data["texto_da_arte"], ["Loja da Ana", "Vestido de capulana", "12.500 Kz", "999 123 456"])
        item = self._item()
        self.assertTrue(item.arte_ref.startswith(f"t/{A}/arte/"))
        self.assertEqual((item.arte_fundo, item.arte_tentativas, item.is_ai_generated), ("gradiente", 1, True))
        self.assertRegex(item.arte_sha256, r"^[0-9a-f]{64}$")

    def test_renderizar_duas_vezes_e_uma_tentativa(self) -> None:
        for _ in range(2):
            self.assertTrue(self.mundo.invocar("generate_art", {"referencia": self.ref}).ok)
        self.assertEqual(self._item().arte_tentativas, 1)

    def test_tres_tentativas_com_alerta_de_custo_e_a_quarta_recusa(self) -> None:
        alertas = []
        for i in range(3):
            r = self.mundo.invocar("generate_art", {"referencia": self.ref, "nova": i > 0})
            self.assertTrue(r.ok, r.error)
            alertas.append(r.data["alerta_de_custo"])
        self.assertEqual(alertas, [False, True, True])
        r = self.mundo.invocar("generate_art", {"referencia": self.ref, "nova": True})
        self.assertEqual((r.error.codigo, r.error.detalhe), ("LIMIT_EXCEEDED", "tentativas_esgotadas"))

    def test_o_fundo_gerado_consome_imagens_mes_e_soma_o_custo(self) -> None:
        mundo = MundoDaArte(gerador_de_fundos=GeradorDeFundosDuplo(True, False))
        ref = mundo.item_com_legenda()
        r = mundo.invocar("generate_art", {"referencia": ref})
        self.assertTrue(r.ok, r.error)
        self.assertEqual((r.data["arte_fundo"], r.data["custo_usd"]), ("gerado", "0.0672"))
        self.assertEqual(len(mundo.repo.imagens[A]), 1)

    def test_sem_imagens_mes_a_arte_sai_com_o_fundo_do_template(self) -> None:
        mundo = MundoDaArte(gerador_de_fundos=GeradorDeFundosDuplo(False), limite_de_imagens=0)
        ref = mundo.item_com_legenda()
        r = mundo.invocar("generate_art", {"referencia": ref})
        self.assertTrue(r.ok, r.error)
        self.assertEqual(r.data["arte_fundo"], "gradiente")
        self.assertEqual(mundo.gerador_de_fundos.pedidos, [])

    def test_sem_sto_ligado_nada_se_gera(self) -> None:
        mundo = MundoDaArte()
        ref = mundo.item_com_legenda()
        portas_sem_sto = social_tools.PortasDoSocial(repositorio=lambda _l: mundo.repo, screening=mundo.screening)
        executor = social_tools.executores(portas_sem_sto, lambda: AGORA)["generate_art"]
        pedido = type("P", (), {"ligacao": object(), "ctx": mundo.ctx(), "args": social_tools.ArgumentosDeGenerateArt(referencia=ref)})()
        with self.assertRaises(social_tools.ErroDeBackend) as erro:
            executor(pedido)
        self.assertEqual(erro.exception.detalhe, "arte_por_ligar")

    def test_pedir_duas_vezes_da_a_mesma_accao_e_aprovar_duas_vezes_um_evento(self) -> None:
        self.assertTrue(self.mundo.invocar("generate_art", {"referencia": self.ref}).ok)
        um = self.mundo.invocar("request_approval", {"referencia": self.ref})
        dois = self.mundo.invocar("request_approval", {"referencia": self.ref})
        self.assertTrue(um.ok and dois.ok, (um.error, dois.error))
        self.assertEqual(um.data["action_id"], dois.data["action_id"])
        self.assertEqual(self._item().estado, PENDENTE_APROVACAO)
        action_id = um.data["action_id"]
        self.mundo.accoes.confirmar(action_id)
        primeira, segunda = self.mundo.aprovar(action_id), self.mundo.aprovar(action_id)
        self.assertTrue(primeira.ok and segunda.ok, (primeira.error, segunda.error))
        # O segundo toque e o *replay* do passo 5: o backend nao corre outra vez.
        self.assertTrue(segunda.idempotent_replay)
        self.assertEqual(self._item().estado, APROVADO)
        self.assertEqual(len(self.mundo.repo.eventos), 1)
        tenant, evento = self.mundo.repo.eventos[0]
        self.assertEqual((tenant, evento.content_item_id, evento.versao), (A, self._item().content_item_id, self._item().versao))

    def test_a_revisao_reforcada_pede_uma_confirmacao_a_mais(self) -> None:
        item = self._item()
        self.mundo.repo.itens[item.content_item_id] = type(item)(**{**vars(item), "revisao_reforcada": True})
        self.mundo.invocar("generate_art", {"referencia": self.ref})
        primeira = self.mundo.invocar("request_approval", {"referencia": self.ref}).data["action_id"]
        self.mundo.accoes.confirmar(primeira)
        r = self.mundo.aprovar(primeira)
        self.assertTrue(r.ok, r.error)
        self.assertTrue(r.data["confirmacao_extra"])
        self.assertEqual(self._item().estado, PENDENTE_APROVACAO)
        self.assertEqual(self.mundo.repo.eventos, [])
        segunda = r.data["action_id"]
        self.assertNotEqual(segunda, primeira)
        self.assertTrue(self.mundo.accoes.linhas[segunda]["ref"].endswith("/reforcada"))
        self.mundo.accoes.confirmar(segunda)
        self.assertTrue(self.mundo.aprovar(segunda).ok)
        self.assertEqual(self._item().estado, APROVADO)
        self.assertEqual(len(self.mundo.repo.eventos), 1)

    def test_sem_o_botao_a_aprovacao_nao_corre(self) -> None:
        self.mundo.invocar("generate_art", {"referencia": self.ref})
        action_id = self.mundo.invocar("request_approval", {"referencia": self.ref}).data["action_id"]
        r = self.mundo.invocar("approve_content", {"action_id": action_id}, allowed=tuple(social_tools.MODELOS))
        self.assertFalse(r.ok)
        r = self.mundo.aprovar(action_id)  # botao certo, accao ainda pendente
        self.assertEqual(r.error.detalhe, "accao_por_confirmar")
        self.assertEqual(self._item().estado, PENDENTE_APROVACAO)

    def test_uma_edicao_depois_da_aprovacao_invalida_o_botao_antigo(self) -> None:
        self.mundo.invocar("generate_art", {"referencia": self.ref})
        antigo = self.mundo.invocar("request_approval", {"referencia": self.ref}).data["action_id"]
        self.mundo.accoes.confirmar(antigo)
        self.assertTrue(self.mundo.aprovar(antigo).ok)
        editado = self.mundo.invocar("request_approval", {"referencia": self.ref, "legenda": "Vestidos de capulana, venha ver."})
        self.assertTrue(editado.ok, editado.error)
        self.assertEqual(self._item().estado, PENDENTE_APROVACAO)
        self.assertNotEqual(editado.data["action_id"], antigo)
        # O botao antigo ja correu: o passo 5 devolve o resultado guardado, e o
        # item continua pendente da legenda nova — nenhum evento novo.
        r = self.mundo.aprovar(antigo)
        self.assertTrue(r.idempotent_replay)
        self.assertEqual(self._item().estado, PENDENTE_APROVACAO)
        self.assertEqual(len(self.mundo.repo.eventos), 1)
        novo = editado.data["action_id"]
        self.mundo.accoes.confirmar(novo)
        self.assertTrue(self.mundo.aprovar(novo).ok)
        self.assertEqual(len(self.mundo.repo.eventos), 2)

    def test_outra_arte_num_item_pendente_invalida_o_botao(self) -> None:
        self.mundo.invocar("generate_art", {"referencia": self.ref})
        antigo = self.mundo.invocar("request_approval", {"referencia": self.ref}).data["action_id"]
        self.assertTrue(self.mundo.invocar("generate_art", {"referencia": self.ref, "nova": True}).ok)
        self.assertIsNone(self._item().aprovacao_hash)
        self.mundo.accoes.confirmar(antigo)
        self.assertEqual(self.mundo.aprovar(antigo).error.detalhe, "aprovacao_invalidada")
        novo = self.mundo.invocar("request_approval", {"referencia": self.ref}).data["action_id"]
        self.assertNotEqual(novo, antigo)

    def test_a_legenda_do_dono_passa_pelos_numeros_e_pelo_screening(self) -> None:
        self.mundo.invocar("generate_art", {"referencia": self.ref})
        r = self.mundo.invocar("request_approval", {"referencia": self.ref, "legenda": "Vestidos a 9.900 Kz so hoje."})
        self.assertEqual(r.error.detalhe, "faltam_factos")
        r = self.mundo.invocar("request_approval", {"referencia": self.ref, "legenda": "Vestidos a 12.500 Kz, venha ver."})
        self.assertTrue(r.ok, r.error)
        bloqueado = MundoDaArte()
        bloqueado.screening.por_texto = {"pistola": "bloqueada"}
        ref = bloqueado.item_com_legenda()
        bloqueado.invocar("generate_art", {"referencia": ref})
        r = bloqueado.invocar("request_approval", {"referencia": ref, "legenda": "Temos pistola de agua."})
        self.assertEqual(r.error.detalhe, "categoria_bloqueada")

    def test_o_item_de_outro_tenant_e_desconhecido(self) -> None:
        self.mundo.com_perfil(B)
        for nome in ("generate_art", "request_approval", "reject_content", "deliver_content"):
            r = self.mundo.invocar(nome, {"referencia": self.ref}, tenant=B)
            self.assertEqual(r.error.detalhe, "item_desconhecido", nome)

    def test_entregar_duas_vezes_da_uma_entrega_e_os_termos_so_na_primeira(self) -> None:
        r = self.mundo.invocar("deliver_content", {"referencia": self.ref})
        self.assertEqual(r.error.detalhe, "por_aprovar")
        self.mundo.invocar("generate_art", {"referencia": self.ref})
        action_id = self.mundo.invocar("request_approval", {"referencia": self.ref}).data["action_id"]
        self.mundo.accoes.confirmar(action_id)
        self.mundo.aprovar(action_id)
        um = self.mundo.invocar("deliver_content", {"referencia": self.ref})
        dois = self.mundo.invocar("deliver_content", {"referencia": self.ref})
        self.assertTrue(um.ok and dois.ok)
        self.assertFalse(um.data["ja_entregue"])
        self.assertTrue(dois.data["ja_entregue"])
        self.assertIsNone(dois.data["entrega"]["termos"])
        entrega = um.data["entrega"]
        self.assertEqual(entrega["legenda"], "Vestidos novos para a semana.")
        self.assertIn("rotulo de IA", entrega["nota"])
        self.assertIn("nao sao exclusivas", entrega["termos"])
        self.assertEqual(self._item().estado, ENTREGUE)
        outro = self.mundo.item_com_legenda(legenda="Outra semana.")
        self.mundo.invocar("generate_art", {"referencia": outro})
        accao = self.mundo.invocar("request_approval", {"referencia": outro}).data["action_id"]
        self.mundo.accoes.confirmar(accao)
        self.mundo.aprovar(accao)
        self.assertIsNone(self.mundo.invocar("deliver_content", {"referencia": outro}).data["entrega"]["termos"])

    # ------------------------------------------------------------ achados da revisao adversarial

    def _com_factos(self, *factos: regras.Facto) -> None:
        perfil = self.mundo.repo.perfis[A]
        self.mundo.repo.perfis[A] = type(perfil)(**{**vars(perfil), "factos": factos})

    def test_r1_a_pre_visualizacao_e_o_texto_guardado_e_nao_os_factos_de_agora(self) -> None:
        self.assertTrue(self.mundo.invocar("generate_art", {"referencia": self.ref, "formato": "retrato"}).ok)
        self._com_factos(regras.Facto("Vestido de capulana a 15.000 Kz"), TELEFONE)
        r = self.mundo.invocar("generate_art", {"referencia": self.ref})
        self.assertIn("12.500 Kz", r.data["texto_da_arte"])
        self.assertNotIn("15.000 Kz", r.data["texto_da_arte"])
        self.assertEqual(r.data["formato"], "retrato")
        # E o preco que ja nao tem facto nao se aprova: nem no pedido, nem no botao.
        r = self.mundo.invocar("request_approval", {"referencia": self.ref})
        self.assertEqual(r.error.detalhe, "arte_desactualizada")

    def test_r1_um_facto_que_muda_depois_do_pedido_trava_o_botao(self) -> None:
        self.mundo.invocar("generate_art", {"referencia": self.ref})
        action_id = self.mundo.invocar("request_approval", {"referencia": self.ref}).data["action_id"]
        self._com_factos(regras.Facto("Vestido de capulana a 15.000 Kz"), TELEFONE)
        self.mundo.accoes.confirmar(action_id)
        self.assertEqual(self.mundo.aprovar(action_id).error.detalhe, "arte_desactualizada")
        self.assertEqual(self._item().estado, PENDENTE_APROVACAO)

    def test_r2_uma_edicao_condicional_pede_a_confirmacao_a_mais(self) -> None:
        self.mundo.invocar("generate_art", {"referencia": self.ref})
        self.mundo.screening.por_texto = {"festa": "condicional"}
        r = self.mundo.invocar("request_approval", {"referencia": self.ref, "legenda": "Vestidos para a festa."})
        self.assertTrue(r.ok, r.error)
        self.assertTrue(self._item().revisao_reforcada)
        self.mundo.accoes.confirmar(r.data["action_id"])
        self.assertTrue(self.mundo.aprovar(r.data["action_id"]).data["confirmacao_extra"])
        self.assertEqual(self._item().estado, PENDENTE_APROVACAO)

    def test_r3_um_item_reforcado_nao_fica_preso_num_botao_ja_usado(self) -> None:
        item = self._item()
        self.mundo.repo.itens[item.content_item_id] = type(item)(**{**vars(item), "revisao_reforcada": True})
        self.mundo.invocar("generate_art", {"referencia": self.ref})
        primeira = self.mundo.invocar("request_approval", {"referencia": self.ref}).data["action_id"]
        self.mundo.accoes.confirmar(primeira)
        self.assertTrue(self.mundo.aprovar(primeira).data["confirmacao_extra"])
        # A segunda perdeu-se (expirou, ou a resposta nao chegou). Um pedido novo
        # nao devolve a primeira, ja confirmada e guardada pelo passo 5.
        outra = self.mundo.invocar("request_approval", {"referencia": self.ref}).data["action_id"]
        self.assertNotEqual(outra, primeira)
        self.mundo.accoes.confirmar(outra)
        extra = self.mundo.aprovar(outra)
        self.assertTrue(extra.data["confirmacao_extra"], extra)
        self.mundo.accoes.confirmar(extra.data["action_id"])
        self.assertTrue(self.mundo.aprovar(extra.data["action_id"]).ok)
        self.assertEqual(self._item().estado, APROVADO)

    def test_r4_o_texto_que_nao_cabe_recusa_antes_de_pedir_o_fundo(self) -> None:
        gerador = GeradorDeFundosDuplo(False)
        mundo = MundoDaArte(gerador_de_fundos=gerador)
        ref = mundo.item_com_legenda()
        perfil = mundo.repo.perfis[A]
        mundo.repo.perfis[A] = type(perfil)(**{**vars(perfil), "nome": "W" * 40})
        r = mundo.invocar("generate_art", {"referencia": ref})
        self.assertEqual(r.error.detalhe, "texto_nao_cabe")
        self.assertEqual(gerador.pedidos, [])
        self.assertEqual(mundo.repo.imagens.get(A, set()), set())

    def test_r6_entregar_outra_vez_reenvia_a_legenda_sem_os_termos(self) -> None:
        self.mundo.invocar("generate_art", {"referencia": self.ref})
        action_id = self.mundo.invocar("request_approval", {"referencia": self.ref}).data["action_id"]
        self.mundo.accoes.confirmar(action_id)
        self.mundo.aprovar(action_id)
        self.assertIsNotNone(self.mundo.invocar("deliver_content", {"referencia": self.ref}).data["entrega"]["termos"])
        dois = self.mundo.invocar("deliver_content", {"referencia": self.ref}).data
        self.assertTrue(dois["ja_entregue"])
        self.assertEqual(dois["entrega"]["legenda"], "Vestidos novos para a semana.")
        self.assertIsNone(dois["entrega"]["termos"])

    def _aprovado(self) -> None:
        self.mundo.invocar("generate_art", {"referencia": self.ref})
        action_id = self.mundo.invocar("request_approval", {"referencia": self.ref}).data["action_id"]
        self.mundo.accoes.confirmar(action_id)
        self.assertTrue(self.mundo.aprovar(action_id).ok)

    def test_kam_256_a_corrida_devolve_a_vista_do_item_ja_entregue(self) -> None:
        self._aprovado()
        gravadas = com_corrida(self.mundo.repo)
        r = self.mundo.invocar("deliver_content", {"referencia": self.ref})
        self.assertTrue(r.ok, r.error)
        self.assertTrue(r.data["ja_entregue"])
        self.assertEqual(r.data["entrega"]["legenda"], "Vestidos novos para a semana.")
        self.assertIn("rotulo de IA", r.data["entrega"]["nota"])
        # Os termos foram com a entrega que ganhou, e nao se repetem nesta.
        self.assertIsNone(r.data["entrega"]["termos"])
        # A mesma vista que o caminho do item que ja vem `entregue` na leitura.
        self.assertEqual(r.data, self.mundo.invocar("deliver_content", {"referencia": self.ref}).data)
        # Uma entrega gravada: a que ganhou. A que perdeu nao escreveu nada.
        self.assertEqual(len(gravadas), 1)
        self.assertEqual(self._item().estado, ENTREGUE)
        self.assertEqual(self._item().versao, gravadas[0].versao)

    def test_r7_dinheiro_no_nome_da_marca_nao_vai_a_arte(self) -> None:
        perfil = self.mundo.repo.perfis[A]
        self.mundo.repo.perfis[A] = type(perfil)(**{**vars(perfil), "nome": "Tudo a 2.500 Kz"})
        r = self.mundo.invocar("generate_art", {"referencia": self.ref})
        self.assertEqual(r.error.detalhe, "faltam_factos")
        # Um numero que nao e dinheiro no nome continua a poder ir.
        self.mundo.repo.perfis[A] = type(perfil)(**{**vars(perfil), "nome": "Loja 24"})
        self.assertTrue(self.mundo.invocar("generate_art", {"referencia": self.ref}).ok)

    def test_r9_o_imagens_mes_esgotado_diz_porque(self) -> None:
        mundo = MundoDaArte(gerador_de_fundos=GeradorDeFundosDuplo(False), limite_de_imagens=0)
        ref = mundo.item_com_legenda()
        self.assertEqual(mundo.invocar("generate_art", {"referencia": ref}).data["motivo_do_fundo"], "sem_imagens")

    def test_rejeitar_fecha_o_item(self) -> None:
        self.mundo.invocar("generate_art", {"referencia": self.ref})
        action_id = self.mundo.invocar("request_approval", {"referencia": self.ref}).data["action_id"]
        self.assertTrue(self.mundo.invocar("reject_content", {"referencia": self.ref}).ok)
        self.assertEqual(self._item().estado, REJEITADO)
        self.mundo.accoes.confirmar(action_id)
        self.assertEqual(self.mundo.aprovar(action_id).error.detalhe, "aprovacao_invalidada")

    def test_a_ligacao_de_vinte_e_quatro_horas_da_arte_nao_abre_noutro_tenant(self) -> None:
        # A ligacao do painel e do ticket credor (D5); a primitiva e a do
        # offboarding, e a chave da arte nao a abre de outro tenant.
        self.mundo.invocar("generate_art", {"referencia": self.ref})
        chave = self._item().arte_ref
        token = ligacao_assinada(b"k" * 32, A, chave, AGORA)
        with self.assertRaises(LigacaoRecusada):
            abrir_ligacao(b"k" * 32, token, B, AGORA, self.mundo.storage)


# ====================================================================== o grafo


class PortaDeAccoesDupla:
    def __init__(self, mundo: MundoDaArte) -> None:
        self.mundo = mundo
        self.tocados: set[str] = set()

    async def confirmar(self, tenant_id: str, contact_id: str, botao: object) -> str:
        from kamba_agr.dono import accoes

        action_id = accoes.accao_do_botao(botao)
        if action_id is None or action_id not in self.mundo.accoes.linhas:
            return "desconhecida"
        if action_id in self.tocados:
            return accoes.JA_CONFIRMADA
        self.tocados.add(action_id)
        self.mundo.accoes.confirmar(action_id)
        return accoes.CONFIRMADA


class TestOGrafo(unittest.TestCase):
    def _turno(self, mundo: MundoDaArte, texto: str = "", *, botao: str | None = None) -> tuple[str, tuple]:
        from kamba_agr.verticais.dono import build_graph
        from kamba_agr.verticais.dono import nos as nos_do_dono
        from kamba_agr.verticais.vendedor import nos as nos_mod
        from test_vendedor import PERSONA, estado_de

        if not hasattr(mundo, "porta"):
            mundo.porta = PortaDeAccoesDupla(mundo)  # type: ignore[attr-defined]
        deps = nos_mod.Dependencias(
            tools=mundo.camada,
            saida=mundo.saida,
            persona=PERSONA,
            tools_permitidas=nos_do_dono.TOOLS_DO_DONO,
            accoes_do_dono=mundo.porta,  # type: ignore[attr-defined]
        )
        troca: dict[str, Any] = {"persona": "dono", "tenant_id": A, "contact_id": CONTACTO}
        tipo = "text"
        if botao is not None:
            troca["botao"] = botao
            tipo = "interactive"
        asyncio.run(build_graph(deps).ainvoke(estado_de(texto, tipo=tipo, **troca)))
        enviado, _chave, botoes = mundo.saida.enviadas[-1]
        return enviado, tuple(botoes)

    def test_da_arte_a_entrega(self) -> None:
        mundo = MundoDaArte()
        ref = mundo.item_com_legenda()
        texto, botoes = self._turno(mundo, botao=f"arte:{ref}")
        self.assertIn("Pre-visualizacao", texto)
        self.assertIn("12.500 Kz", texto)
        self.assertEqual(botoes[1:], (f"editar:{ref}", f"rejeitar:{ref}"))
        self.assertTrue(botoes[0].startswith("confirm:"))
        texto, botoes = self._turno(mundo, botao=botoes[0])
        self.assertIn("Aprovado", texto)
        self.assertEqual(botoes, (f"enviar:{ref}",))
        texto, _ = self._turno(mundo, f"ENVIAR {ref}")
        self.assertIn("Vestidos novos para a semana.", texto)
        self.assertIn("rotulo de IA", texto)
        texto, _ = self._turno(mundo, botao=f"enviar:{ref}")
        self.assertIn("ja lhe foi entregue", texto)
        self.assertIn("Vestidos novos para a semana.", texto)
        self.assertEqual(len(mundo.repo.eventos), 1)

    def test_kam_246_a_arte_vai_como_imagem_na_pre_visualizacao_e_so_na_primeira_entrega(self) -> None:
        mundo = MundoDaArte()
        ref = mundo.item_com_legenda()
        texto, botoes = self._turno(mundo, botao=f"arte:{ref}")
        (item,) = mundo.repo.itens_por_prefixo(A, regras.prefixo_da_referencia(ref))
        arte = item.arte_ref
        # A pre-visualizacao leva a chave do STO da arte do item, e o aviso de que
        # a imagem nao seguia saiu; a nota do rotulo de IA vai no texto.
        media = mundo.saida.medias[-1]
        self.assertIsNotNone(media)
        self.assertTrue(media.startswith(f"t/{A}/arte/"))
        self.assertEqual(media, arte)
        self.assertNotIn("ainda nao segue", texto)
        self.assertIn("rotulo de IA", texto)
        self.assertIn("pagina Social", texto)
        # A aprovacao nao leva imagem.
        self._turno(mundo, botao=botoes[0])
        self.assertIsNone(mundo.saida.medias[-1])
        # A primeira entrega leva-a; a segunda reenvia a legenda sem ela.
        texto, _ = self._turno(mundo, f"ENVIAR {ref}")
        self.assertEqual(mundo.saida.medias[-1], media)
        self.assertNotIn("ainda nao segue", texto)
        self.assertIn("Vestidos novos para a semana.", texto)
        texto, _ = self._turno(mundo, botao=f"enviar:{ref}")
        self.assertIn("ja lhe foi entregue", texto)
        self.assertIsNone(mundo.saida.medias[-1], "entregar duas vezes envia uma imagem")

    def test_kam_256_a_corrida_de_duas_entregas_responde_ao_dono_com_a_legenda(self) -> None:
        mundo = MundoDaArte()
        ref = mundo.item_com_legenda()
        _texto, botoes = self._turno(mundo, botao=f"arte:{ref}")
        self._turno(mundo, botao=botoes[0])
        gravadas = com_corrida(mundo.repo)
        # Antes do KAM-256, a vista da corrida vinha sem a `entrega` e este turno
        # partia com um `KeyError` no `_entregar`.
        texto, _ = self._turno(mundo, f"ENVIAR {ref}")
        self.assertIn("ja lhe foi entregue", texto)
        self.assertIn("Vestidos novos para a semana.", texto)
        self.assertIn("rotulo de IA", texto)
        self.assertNotIn("nao sao exclusivas", texto)
        # A imagem foi com a entrega que ganhou; a que perdeu nao a reenvia.
        self.assertIsNone(mundo.saida.medias[-1])
        self.assertEqual(len(gravadas), 1)
        (item,) = mundo.repo.itens_por_prefixo(A, regras.prefixo_da_referencia(ref))
        self.assertEqual(item.estado, ENTREGUE)

    def test_kam_256_uma_vista_sem_entrega_da_a_frase_de_erro_e_nao_levanta(self) -> None:
        from unittest import mock

        from kamba_agr.verticais.dono import social as social_do_dono

        ref = regras.referencia_do_item(str(uuid.uuid4()))
        for dados in ({"ja_entregue": True}, {"ja_entregue": False, "entrega": None}, {"entrega": {"nota": "x"}}):

            async def deliver(*_a: Any, dados: dict[str, Any] = dados, **_k: Any) -> Any:
                return type("Lido", (), {"ok": True, "data": dados, "error": None})()

            with mock.patch.object(social_do_dono, "_invocar", deliver):
                resposta = asyncio.run(social_do_dono._entregar(None, {}, ref))  # type: ignore[arg-type]
            self.assertEqual(resposta["draft"]["texto"], social_do_dono.MSG_NAO_CONSEGUI, dados)
            self.assertNotIn("media", resposta["draft"], dados)

    def test_kam_246_uma_edicao_pede_outra_vez_a_aprovacao_com_a_mesma_imagem(self) -> None:
        mundo = MundoDaArte()
        ref = mundo.item_com_legenda()
        self._turno(mundo, botao=f"arte:{ref}")
        primeira = mundo.saida.medias[-1]
        self._turno(mundo, f"EDITAR {ref}: Vestidos de capulana para a festa.")
        self.assertEqual(mundo.saida.medias[-1], primeira)

    def test_o_botao_antigo_depois_de_uma_edicao_nao_diz_aprovado(self) -> None:
        mundo = MundoDaArte()
        ref = mundo.item_com_legenda()
        _texto, botoes = self._turno(mundo, botao=f"arte:{ref}")
        antigo = botoes[0]
        self.assertIn("Aprovado", self._turno(mundo, botao=antigo)[0])
        self._turno(mundo, f"EDITAR {ref}: Vestidos de capulana para a festa.")
        texto, _ = self._turno(mundo, botao=antigo)
        self.assertNotIn("Aprovado", texto)
        self.assertIn("ja foi usado", texto)
        texto, _ = self._turno(mundo, f"ENVIAR {ref}")
        self.assertIn("ainda nao foi aprovado", texto)
        self.assertEqual(len(mundo.repo.eventos), 1)

    def test_editar_pelo_texto_e_o_pedido_de_publicacao(self) -> None:
        mundo = MundoDaArte()
        ref = mundo.item_com_legenda()
        self._turno(mundo, botao=f"arte:{ref}")
        texto, _ = self._turno(mundo, botao=f"editar:{ref}")
        self.assertIn("EDITAR", texto)
        texto, botoes = self._turno(mundo, f"EDITAR {ref}: Vestidos de capulana para a festa.")
        self.assertIn("Vestidos de capulana para a festa.", texto)
        self.assertTrue(botoes[0].startswith("confirm:"))
        texto, _ = self._turno(mundo, "publica por mim no instagram")
        self.assertIn("nao publico", texto)

    def test_as_frases_novas_nao_tem_digitos(self) -> None:
        from kamba_agr.verticais.dono import social as conversa

        for nome in dir(conversa):
            valor = getattr(conversa, nome)
            if nome.startswith("MSG_") and isinstance(valor, str):
                self.assertFalse(re.search(r"\d", valor), nome)


if __name__ == "__main__":
    unittest.main()
