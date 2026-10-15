"""Regressoes da revisao adversarial do KAM-011 (`docs/analises/ANALISE-09`).

Cada teste aqui existe porque a revisao mostrou um defeito ou uma mutacao que
sobrevivia. O identificador do achado esta no nome da classe; o espelho
TypeScript e `packages/core-ts/tests/storage.revisao.test.ts`.
"""

from __future__ import annotations

import http.client
import os
import socket
import ssl
import threading
import unittest
from datetime import UTC, datetime, timedelta, timezone
from unittest import mock
from urllib.parse import parse_qs, urlsplit

from storage_apoio import CONFIG_DE_TESTE, CREDENCIAIS_DE_TESTE, montar_s3_em_memoria

from kamba_core.storage import (
    ArmazenamentoIndisponivelError,
    ChaveForaDoTenantError,
    ChaveInvalidaError,
    ConfigDeArmazenamentoError,
    Ctx,
    DestinoSemApdRefError,
    MetaInvalidaError,
    ObjectMeta,
    ObjectRef,
    RespostaDoMotorInvalidaError,
    TenantInvalidoError,
    TtlInvalidoError,
    criar_storage_fake,
    ler_config,
    nova_chave,
    prefixo_do_tenant,
)
from kamba_core.storage.guarda import ArmazenamentoPorTenant, formatar_instante, ler_instante
from kamba_core.storage.motor import InfoBruta, ItemListado, Listagem
from kamba_core.storage.s3 import (
    PARTE_POR_OMISSAO,
    MotorS3,
    PedidoHttp,
    RespostaHttp,
    desescapar_xml,
    transporte_por_http,
)
from kamba_core.storage.sigv4 import assinatura

A = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"
B = "bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb"
CTX_A = Ctx(A)
CTX_B = Ctx(B)
PRAZO = datetime(2026, 10, 13, 8, 30, tzinfo=UTC)
META = ObjectMeta("audio/ogg", "audio", PRAZO)

BOM = {
    "KAMBA_STORAGE_ENDPOINT": "http://seaweedfs:8333",
    "KAMBA_STORAGE_BUCKET": "kamba-dev",
    "KAMBA_STORAGE_REGION": "us-east-1",
    "KAMBA_STORAGE_DESTINO_COUNTRY": "AO",
    "KAMBA_STORAGE_DESTINO_PROVIDER": "seaweedfs_local",
}
FORA = {**BOM, "KAMBA_STORAGE_DESTINO_COUNTRY": "ZA"}


class A1AmbienteDesconhecidoNaoArranca(unittest.TestCase):
    """A regra do `apd_ref` so bloqueia em `prod`: um ambiente que nao e
    exactamente um dos tres desligava-a em silencio."""

    def test_um_ambiente_fora_do_dominio_e_recusado_e_nao_tratado_como_nao_prod(self) -> None:
        for ambiente in ("PROD", "Prod", "prod ", " prod", "production", "producao", "", None, 7, "prod\n"):
            for env in (FORA, BOM):
                with self.subTest(ambiente=ambiente, country=env["KAMBA_STORAGE_DESTINO_COUNTRY"]):
                    with self.assertRaises(ConfigDeArmazenamentoError) as apanhado:
                        ler_config(ambiente=ambiente, env=env)  # type: ignore[arg-type]
                    self.assertIn("ambiente desconhecido", str(apanhado.exception))

    def test_os_tres_ambientes_canonicos_continuam_a_valer(self) -> None:
        for ambiente in ("dev", "staging"):
            self.assertEqual(len(ler_config(ambiente=ambiente, env=FORA).avisos), 1)
        with self.assertRaises(DestinoSemApdRefError):
            ler_config(ambiente="prod", env=FORA)

    def test_uma_subclasse_de_str_nao_passa_por_ambiente(self) -> None:
        # Igual a tudo enquanto o validam, e a nada quando a regra pergunta se
        # e `prod`: com `isinstance`, passava a validacao e desligava a regra.
        class Camaleao(str):
            perguntas = 0

            def __eq__(self, outro: object) -> bool:
                type(self).perguntas += 1
                return type(self).perguntas == 1

            __hash__ = str.__hash__

        with self.assertRaises(ConfigDeArmazenamentoError) as apanhado:
            ler_config(ambiente=Camaleao("prod"), env=FORA)
        self.assertIn("ambiente desconhecido", str(apanhado.exception))


class A2SubclassesDeTextoEDeInteiro(unittest.TestCase):
    """Uma subclasse de `str` passava a validacao com um valor e entrava na
    chave com outro; uma de `int` respondia as comparacoes como queria."""

    def setUp(self) -> None:
        fake = criar_storage_fake()
        self.storage = fake.storage
        self.ref_b = self.storage.put(CTX_B, nova_chave(CTX_B, "audio"), b"canario de B", META)
        self.ref_a = self.storage.put(CTX_A, nova_chave(CTX_A, "audio"), b"de A", META)

    def test_tenant_que_se_formata_como_outro(self) -> None:
        class Mentiroso(str):
            def __format__(self, _spec: str) -> str:
                return B

        ctx = Ctx(Mentiroso(A))
        with self.assertRaises(TenantInvalidoError):
            self.storage.list(ctx, f"t/{B}/")
        with self.assertRaises(TenantInvalidoError):
            self.storage.get(ctx, self.ref_b)
        with self.assertRaises(TenantInvalidoError):
            prefixo_do_tenant(ctx)

    def test_chave_e_prefixo_que_mudam_de_valor(self) -> None:
        chave_b = self.ref_b.key

        class Mutante(str):
            def __str__(self) -> str:
                return chave_b

            def __format__(self, _spec: str) -> str:
                return chave_b

        for operacao in (
            lambda: self.storage.sign_url(CTX_A, ObjectRef(Mutante(self.ref_a.key), 0), ttl_seconds=60),
            lambda: self.storage.get(CTX_A, ObjectRef(Mutante(self.ref_a.key), 0)),
            lambda: self.storage.delete(CTX_A, ObjectRef(Mutante(self.ref_a.key), 0)),
            lambda: self.storage.put(CTX_A, Mutante(self.ref_a.key), b"x", META),
            lambda: self.storage.list(CTX_A, Mutante(f"t/{A}/")),
        ):
            with self.assertRaises(ChaveInvalidaError):
                operacao()
        with self.assertRaises(MetaInvalidaError):
            nova_chave(CTX_A, Mutante("audio"))
        # O objecto de B continua la, e A nunca o leu.
        self.assertEqual(b"".join(self.storage.get(CTX_B, self.ref_b)), b"canario de B")

    def test_ttl_e_limite_que_mentem_nas_comparacoes(self) -> None:
        class Enorme(int):
            def __lt__(self, _o: object) -> bool:
                return False

            def __gt__(self, _o: object) -> bool:
                return False

        with self.assertRaises(TtlInvalidoError):
            self.storage.sign_url(CTX_A, self.ref_a, ttl_seconds=Enorme(10**12))
        with self.assertRaises(MetaInvalidaError):
            self.storage.list(CTX_A, f"t/{A}/", limite=Enorme(10**12))
        # Sem limite dado, vale o de omissao — como do lado TypeScript.
        self.assertEqual(len(self.storage.list(CTX_A, f"t/{A}/", limite=None)), 1)

    def test_o_motor_que_devolve_uma_chave_que_nao_e_texto_puro(self) -> None:
        class Motor:
            nome = "mentiroso"

            def list(self, _prefixo: str, _maximo: int) -> Listagem:
                class Disfarce(str):
                    def startswith(self, *_a: object) -> bool:
                        return True

                return Listagem((ItemListado(Disfarce(f"t/{B}/audio/2026/10/x"), 1),), False)

        with self.assertRaises(RespostaDoMotorInvalidaError):
            ArmazenamentoPorTenant(Motor()).list(CTX_A, f"t/{A}/")  # type: ignore[arg-type]


class A3ACausaDeUmErroDeRedeNaoFicaPendurada(unittest.TestCase):
    def test_nem_em_cause_nem_em_context(self) -> None:
        alvo, servidor, _ = montar_s3_em_memoria()
        ref = alvo.storage.put(CTX_A, nova_chave(CTX_A, "audio"), b"1234", META)

        def rede_em_baixo(p: PedidoHttp) -> RespostaHttp | None:
            raise OSError(f"falhou {p.url} {p.cabecalhos['authorization']}")

        servidor.interceptar = rede_em_baixo
        for operacao in (
            lambda: alvo.storage.get(CTX_A, ref),
            lambda: alvo.storage.head(CTX_A, ref),
            lambda: alvo.storage.delete(CTX_A, ref),
            lambda: alvo.storage.list(CTX_A, prefixo_do_tenant(CTX_A)),
            lambda: alvo.storage.put(CTX_A, nova_chave(CTX_A, "audio"), b"x", META),
        ):
            with self.assertRaises(ArmazenamentoIndisponivelError) as apanhado:
                operacao()
            erro = apanhado.exception
            self.assertIsNone(erro.__cause__)
            self.assertIsNone(erro.__context__, "o erro de rede, com a URL, ficava aqui")
            self.assertIsNone(erro.estado)


class A4OTransporteVerificaCertificadosETemTempoLimite(unittest.TestCase):
    def test_https_verifica_o_certificado_e_o_nome_do_anfitriao(self) -> None:
        vistos: list[ssl.SSLContext] = []

        class Falsa:
            def __init__(self, _host: str, _porta: int | None, *, timeout: float, context: ssl.SSLContext) -> None:
                vistos.append(context)
                self.timeout = timeout

            def request(self, *_a: object, **_k: object) -> None:
                raise OSError("sem rede neste teste")

            def close(self) -> None:
                pass

        with mock.patch.object(http.client, "HTTPSConnection", Falsa):
            with self.assertRaises(OSError):
                transporte_por_http(3)(PedidoHttp("GET", "https://s3.exemplo.invalid/x", {}))
        self.assertEqual(len(vistos), 1)
        self.assertEqual(vistos[0].verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(vistos[0].check_hostname)

    def test_um_servidor_que_nao_responde_nao_pendura_o_pedido(self) -> None:
        # Aceita a ligacao e cala-se.
        escuta = socket.socket()
        escuta.bind(("127.0.0.1", 0))
        escuta.listen(1)
        aceites: list[socket.socket] = []
        fio = threading.Thread(target=lambda: aceites.append(escuta.accept()[0]), daemon=True)
        fio.start()
        try:
            motor = MotorS3(
                endpoint=f"http://127.0.0.1:{escuta.getsockname()[1]}",
                bucket="kamba-teste",
                regiao="ao-teste-1",
                credenciais=lambda: CREDENCIAIS_DE_TESTE,
                tempo_limite_s=0.5,
            )
            # Num fio a parte, com prazo: sem tempo limite no transporte este
            # pedido nao volta nunca, e um teste que fica pendurado nao falha.
            erros: list[BaseException] = []

            def pedir() -> None:
                try:
                    motor.head(f"t/{A}/audio/x")
                except BaseException as erro:  # noqa: BLE001
                    erros.append(erro)

            pedido = threading.Thread(target=pedir, daemon=True)
            pedido.start()
            pedido.join(15)
            self.assertFalse(pedido.is_alive(), "o pedido ficou pendurado: nao ha tempo limite")
            self.assertEqual(len(erros), 1)
            self.assertIsInstance(erros[0], ArmazenamentoIndisponivelError)
        finally:
            for s in aceites:
                s.close()
            escuta.close()


class A5EA6InstantesQueSeLeemDeVolta(unittest.TestCase):
    def test_so_a_forma_canonica_e_so_datas_que_existem(self) -> None:
        self.assertEqual(ler_instante("2026-10-13T08:30:00.000Z"), PRAZO)
        for texto in (
            "2026-02-30T00:00:00.000Z",
            "2026-01-01T24:00:00.000Z",
            "0000-01-01T00:00:00.000Z",
            "0999-01-01T00:00:00.000Z",
            "2026-10-13T08:30:00Z",
            "2026-10-13T08:30:00.000+00:00",
            "2026-10-13T08:30:00.000000Z",
            "+010000-01-01T00:00:00.000Z",
            "2026-10-13T08:30:00.000Z\n",
            "",
            None,
            7,
        ):
            with self.subTest(texto=texto):
                self.assertIsNone(ler_instante(texto))

    def test_put_recusa_um_prazo_que_o_head_nao_leria(self) -> None:
        fake = criar_storage_fake()
        key = nova_chave(CTX_A, "audio")
        for prazo in (
            datetime(1, 1, 1, tzinfo=timezone(timedelta(hours=5))),
            datetime(999, 12, 31, tzinfo=UTC),
            datetime(9999, 12, 31, 23, 59, tzinfo=timezone(timedelta(hours=-5))),
        ):
            with self.subTest(prazo=prazo), self.assertRaises(MetaInvalidaError):
                fake.storage.put(CTX_A, key, b"x", ObjectMeta("audio/ogg", "audio", prazo))
        self.assertEqual(fake.total(), 0)
        # Os extremos que cabem escrevem-se e leem-se.
        for prazo in (datetime(1000, 1, 1, tzinfo=UTC), datetime(9999, 12, 31, 23, 59, 59, tzinfo=UTC)):
            ref = fake.storage.put(CTX_A, key, b"x", ObjectMeta("audio/ogg", "audio", prazo))
            self.assertEqual(fake.storage.head(CTX_A, ref).retain_until, prazo)
            self.assertEqual(ler_instante(formatar_instante(prazo)), prazo)

    def test_head_recusa_datas_impossiveis_vindas_do_servidor(self) -> None:
        class Motor:
            nome = "x"
            valor = ""

            def head(self, _chave: str) -> InfoBruta:
                return InfoBruta(1, "audio/ogg", {"classe": "audio", "retain-until": self.valor})

        motor = Motor()
        storage = ArmazenamentoPorTenant(motor)  # type: ignore[arg-type]
        ref = ObjectRef(nova_chave(CTX_A, "audio"), 1)
        for valor in ("2026-02-30T00:00:00.000Z", "2026-01-01T24:00:00.000Z", "0000-01-01T00:00:00.000Z", "2026-10-13T08:30:00Z"):
            motor.valor = valor
            with self.subTest(valor=valor), self.assertRaises(RespostaDoMotorInvalidaError):
                storage.head(CTX_A, ref)


class A5CorpoQueNaoEDeBytes(unittest.TestCase):
    def test_um_bloco_de_texto_e_recusado_pela_porta_e_nao_pelo_motor(self) -> None:
        for alvo in (criar_storage_fake().storage, montar_s3_em_memoria()[0].storage):
            for corpo in (["abc"], [b"ab", "c"], [b"ab", 7], iter([None])):
                with self.subTest(alvo=alvo.nome, corpo=corpo), self.assertRaises(MetaInvalidaError):
                    alvo.put(CTX_A, nova_chave(CTX_A, "audio"), corpo, META)  # type: ignore[arg-type]
            self.assertEqual(alvo.list(CTX_A, prefixo_do_tenant(CTX_A)), [])
            # bytearray e memoryview, em blocos, servem.
            ref = alvo.put(CTX_A, nova_chave(CTX_A, "audio"), [bytearray(b"ab"), memoryview(b"c")], META)
            self.assertEqual(b"".join(alvo.get(CTX_A, ref)), b"abc")


class A5ConfiguracaoIgualDosDoisLados(unittest.TestCase):
    """Os mesmos casos, com o mesmo veredicto, em `storage.revisao.test.ts`."""

    def test_endpoints_de_fronteira(self) -> None:
        recusados = (
            "http://h/?", "http://h/#", "http:h", "http://h/./", "http:\\\\h", "http://h:0",
            "http://exämple.com", "http://h.", "http://a_b:9000", "HTTP://h", "http://H",
            "http://h:65536", "http://h:123456", "http://h//", "http://[::1", "http://-h",
            "http://h:", "http://h:80:80", "http://u@h", "http://h /",
        )
        for endpoint in recusados:
            with self.subTest(endpoint=endpoint), self.assertRaises(ConfigDeArmazenamentoError):
                ler_config(ambiente="dev", env={**BOM, "KAMBA_STORAGE_ENDPOINT": endpoint})
        aceites = {
            "http://h": "http://h",
            "http://h/": "http://h",
            "http://h:80": "http://h",
            "https://h:443/": "https://h",
            "http://h:443": "http://h:443",
            "https://s3.exemplo.co.ao:8443": "https://s3.exemplo.co.ao:8443",
            "http://127.0.0.1:8333": "http://127.0.0.1:8333",
            "http://0x7f.1": "http://0x7f.1",
            "http://[::1]:8333": "http://[::1]:8333",
            "http://h:65535": "http://h:65535",
        }
        for endpoint, esperado in aceites.items():
            with self.subTest(endpoint=endpoint):
                self.assertEqual(
                    ler_config(ambiente="dev", env={**BOM, "KAMBA_STORAGE_ENDPOINT": endpoint}).endpoint,
                    esperado,
                )

    def test_so_espaco_tabulacao_e_mudanca_de_linha_se_tiram_das_pontas(self) -> None:
        self.assertEqual(
            ler_config(ambiente="dev", env={**BOM, "KAMBA_STORAGE_DESTINO_COUNTRY": " \tAO\r\n"}).destino.country,
            "AO",
        )
        for country in ("AO\x1f", "AO﻿", " AO", "AO ", "AO\x0b"):
            with self.subTest(country=repr(country)), self.assertRaises(ConfigDeArmazenamentoError):
                ler_config(ambiente="dev", env={**BOM, "KAMBA_STORAGE_DESTINO_COUNTRY": country})


class A5OFakeRecusaOMesmoDosDoisLados(unittest.TestCase):
    def test_assinatura_em_maiusculas_com_lixo_e_expira_fraccionado(self) -> None:
        fake = criar_storage_fake()
        ref = fake.storage.put(CTX_A, nova_chave(CTX_A, "audio"), b"abc", META)
        url = fake.storage.sign_url(CTX_A, ref, ttl_seconds=60)
        base, _, query = url.partition("?")
        q = {n: v[0] for n, v in parse_qs(query).items()}
        self.assertEqual(fake.buscar(url).estado, 200)
        for expira, assinatura_ in (
            (q["expira"], q["assinatura"].upper()),
            (q["expira"], q["assinatura"] + "zz"),
            (q["expira"], q["assinatura"] + "00"),
            (q["expira"] + ".0", q["assinatura"]),
            ("+" + q["expira"], q["assinatura"]),
            (" " + q["expira"], q["assinatura"]),
        ):
            with self.subTest(expira=expira, assinatura=assinatura_[:8]):
                self.assertEqual(fake.buscar(f"{base}?expira={expira}&assinatura={assinatura_}").estado, 403)


class A9XmlHostilNaoRebenta(unittest.TestCase):
    def test_um_ponto_de_codigo_impossivel_fica_como_veio(self) -> None:
        for texto in ("&#x110000;", "&#1114112;", "&#xFFFFFFFFFFFF;", "&#99999999999999999999;"):
            self.assertEqual(desescapar_xml(texto), texto)
        self.assertEqual(desescapar_xml("&#x41;&#66;"), "AB")

    def test_uma_listagem_com_essa_entidade_e_recusada_pela_guarda_e_nao_por_um_erro_cru(self) -> None:
        alvo, servidor, _ = montar_s3_em_memoria()
        servidor.interceptar = lambda _p: RespostaHttp(
            200,
            {},
            (
                b"<ListBucketResult><IsTruncated>false</IsTruncated><Contents>"
                b"<Key>&#x110000;</Key><Size>1</Size></Contents></ListBucketResult>",
            ),
        )
        with self.assertRaises(RespostaDoMotorInvalidaError):
            alvo.storage.list(CTX_A, prefixo_do_tenant(CTX_A))


class MutacoesQueSobreviviam(unittest.TestCase):
    def test_r10_o_limite_pedido_chega_ao_servidor_como_max_keys(self) -> None:
        alvo, servidor, _ = montar_s3_em_memoria()
        for _ in range(3):
            alvo.storage.put(CTX_A, nova_chave(CTX_A, "audio"), b"x", META)
        servidor.pedidos.clear()
        alvo.storage.list(CTX_A, prefixo_do_tenant(CTX_A), limite=7)
        alvo.storage.list(CTX_A, prefixo_do_tenant(CTX_A))
        alvo.storage.list(CTX_A, prefixo_do_tenant(CTX_A), limite=5000)
        self.assertEqual(
            [parse_qs(urlsplit(p.url).query)["max-keys"][0] for p in servidor.pedidos],
            ["7", "1000", "1000"],
        )

    def test_r14_um_404_numa_listagem_nao_e_objecto_inexistente(self) -> None:
        alvo, servidor, _ = montar_s3_em_memoria()
        for corpo in ("<Error><Code>NoSuchKey</Code></Error>", ""):
            servidor.interceptar = lambda _p, c=corpo: RespostaHttp(404, {}, (c.encode(),) if c else ())
            with self.assertRaises(ArmazenamentoIndisponivelError) as apanhado:
                alvo.storage.list(CTX_A, prefixo_do_tenant(CTX_A))
            self.assertEqual(apanhado.exception.estado, 404)

    def test_r15_os_espacos_de_um_cabecalho_sao_normalizados_antes_de_assinar(self) -> None:
        def assinar(valor: str) -> str:
            return assinatura(
                metodo="GET",
                url="http://s3.teste.invalid:8333/kamba-teste/t/x",
                cabecalhos={"host": "s3.teste.invalid:8333", "content-type": valor},
                hash_do_corpo="UNSIGNED-PAYLOAD",
                regiao="ao-teste-1",
                quando="20261012T090000Z",
                segredo="valor-de-teste",
            )[0]

        self.assertEqual(assinar("audio/ogg;  codecs=opus"), assinar("audio/ogg; codecs=opus"))
        self.assertEqual(assinar("  audio/ogg; codecs=opus \t"), assinar("audio/ogg; codecs=opus"))
        self.assertNotEqual(assinar("audio/ogg;codecs=opus"), assinar("audio/ogg; codecs=opus"))
        # Valor fixado, igual ao do lado TypeScript.
        self.assertEqual(
            assinar("audio/ogg;  codecs=opus"),
            R15_PARTILHADO,
        )

    def test_r26_com_a_parte_por_omissao_10_mb_vao_num_pedido_e_25_mb_em_duas_partes(self) -> None:
        self.assertEqual(PARTE_POR_OMISSAO, 16 * 1024 * 1024)
        alvo, servidor, _ = montar_s3_em_memoria()
        alvo.storage.put(CTX_A, nova_chave(CTX_A, "audio"), os.urandom(10 * 1024 * 1024), META)
        self.assertEqual([p.metodo for p in servidor.pedidos], ["PUT"])
        servidor.pedidos.clear()
        alvo.storage.put(CTX_A, nova_chave(CTX_A, "audio"), os.urandom(25 * 1024 * 1024), META)
        self.assertEqual([p.metodo for p in servidor.pedidos], ["POST", "PUT", "PUT", "POST"])
        self.assertEqual(len(servidor.pedidos[1].corpo or b""), 16 * 1024 * 1024)

    def test_a_query_vai_na_rede_em_rfc_3986_como_do_lado_typescript(self) -> None:
        alvo, servidor, _ = montar_s3_em_memoria(pagina=1)
        for _ in range(2):
            alvo.storage.put(CTX_A, nova_chave(CTX_A, "audio"), b"x", META)
        servidor.pedidos.clear()
        # Um servidor que devolve um token de continuacao com caracteres dificeis.
        original = servidor.interceptar
        primeira = [True]

        def token_dificil(p: PedidoHttp) -> RespostaHttp | None:
            if primeira[0]:
                primeira[0] = False
                return RespostaHttp(
                    200,
                    {},
                    (
                        b"<ListBucketResult><IsTruncated>true</IsTruncated>"
                        b"<NextContinuationToken>a b+c~*/=</NextContinuationToken></ListBucketResult>",
                    ),
                )
            return RespostaHttp(200, {}, (b"<ListBucketResult><IsTruncated>false</IsTruncated></ListBucketResult>",))

        servidor.interceptar = token_dificil
        alvo.storage.list(CTX_A, prefixo_do_tenant(CTX_A))
        servidor.interceptar = original
        self.assertIn("continuation-token=a%20b%2Bc~%2A%2F%3D", servidor.pedidos[1].url)
        self.assertIn(f"prefix=t%2F{A}%2F", servidor.pedidos[0].url)
        self.assertEqual(CONFIG_DE_TESTE.bucket, "kamba-teste")


#: Ver `test_r15…`. Igual em `storage.revisao.test.ts`.
R15_PARTILHADO = "18251ed12bcdbe6d47d12cd6d986d555a3f9e592bd91d15b1b6c6d54adcad741"


class ChaveForaDoTenantContinuaAFuncionar(unittest.TestCase):
    def test_a_metade_positiva_depois_das_correccoes(self) -> None:
        fake = criar_storage_fake()
        ref_b = fake.storage.put(CTX_B, nova_chave(CTX_B, "audio"), b"b", META)
        with self.assertRaises(ChaveForaDoTenantError):
            fake.storage.get(CTX_A, ref_b)
        self.assertEqual(b"".join(fake.storage.get(CTX_B, ref_b)), b"b")


if __name__ == "__main__":
    unittest.main()
