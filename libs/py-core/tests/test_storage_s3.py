"""O motor S3 por dentro, do lado Python (KAM-011): assinatura, envio em partes,
paginacao e traducao de erros.

A bateria de contrato prova o comportamento visto pela porta. Aqui prova-se o
que ela nao ve: **que pedidos** o motor faz, e o que faz quando o servidor
responde mal. Espelho de `packages/core-ts/tests/storage.s3.test.ts`.
"""

from __future__ import annotations

import http.server
import os
import threading
import unittest
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

from storage_apoio import (
    CONFIG_DE_TESTE,
    CREDENCIAIS_DE_TESTE,
    S3EmMemoria,
    montar_s3_em_memoria,
)

from kamba_core.storage import (
    ArmazenamentoIndisponivelError,
    Ctx,
    ListagemTruncadaError,
    ObjectMeta,
    ObjectoInexistenteError,
    ObjectRef,
    nova_chave,
    prefixo_do_tenant,
)
from kamba_core.storage.motor import MetaBruta
from kamba_core.storage.s3 import (
    PARTE_MINIMA,
    MotorS3,
    PedidoHttp,
    RespostaHttp,
    desescapar_xml,
    elemento_xml,
    transporte_por_http,
)
from kamba_core.storage.sigv4 import (
    Credenciais,
    anfitriao,
    assinar_pedido,
    assinatura,
    caminho_canonico,
    codificar,
    data_amz,
    presignar_get,
    query_canonica,
)

CTX = Ctx("aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa")
META = ObjectMeta("audio/ogg", "audio", datetime(2026, 10, 13, 8, 30, tzinfo=UTC))
AGORA = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)

#: Assinatura fixada de um pedido fixo. E o mesmo valor que esta em
#: `packages/core-ts/tests/storage.s3.test.ts`: as duas implementacoes foram
#: escritas em separado e tem de dar o mesmo. A do lado TypeScript e aceite por
#: um SeaweedFS 4.48 (`docs/evidencia/KAM-011-seaweedfs.md`).
VECTOR_PARTILHADO = "b0f4568593201ae85b731edd60ec680731274d72d131c016189e5ad4bdee6ae2"


def resposta(estado: int, corpo: str = "", cabecalhos: dict[str, str] | None = None) -> RespostaHttp:
    return RespostaHttp(estado, cabecalhos or {}, (corpo.encode(),) if corpo else ())


def erro_xml(codigo: str) -> str:
    return f"<Error><Code>{codigo}</Code></Error>"


def metodos(servidor: S3EmMemoria) -> list[str]:
    saida = []
    for p in servidor.pedidos:
        q = parse_qs(urlsplit(p.url).query, keep_blank_values=True)
        if "uploads" in q:
            saida.append(f"{p.metodo} uploads")
        elif "partNumber" in q:
            saida.append(f"{p.metodo} parte {q['partNumber'][0]}")
        elif "uploadId" in q:
            saida.append(f"{p.metodo} envio")
        else:
            saida.append(p.metodo)
    return saida


def parametro(pedido: PedidoHttp, nome: str) -> str | None:
    valores = parse_qs(urlsplit(pedido.url).query, keep_blank_values=True).get(nome)
    return None if valores is None else valores[0]


class EnvioEmPartes(unittest.TestCase):
    def test_a_fronteira_ate_uma_parte_um_pedido_um_byte_acima_duas(self) -> None:
        alvo, servidor, _ = montar_s3_em_memoria(tamanho_da_parte=PARTE_MINIMA)
        alvo.storage.put(CTX, nova_chave(CTX, "audio"), os.urandom(PARTE_MINIMA), META)
        self.assertEqual(metodos(servidor), ["PUT"])

        alvo, servidor, _ = montar_s3_em_memoria(tamanho_da_parte=PARTE_MINIMA)
        dados = os.urandom(PARTE_MINIMA + 1)
        ref = alvo.storage.put(CTX, nova_chave(CTX, "audio"), dados, META)
        self.assertEqual(
            metodos(servidor), ["POST uploads", "PUT parte 1", "PUT parte 2", "POST envio"]
        )
        self.assertEqual(len(servidor.pedidos[1].corpo or b""), PARTE_MINIMA)
        self.assertEqual(len(servidor.pedidos[2].corpo or b""), 1)
        self.assertEqual(ref.tamanho, PARTE_MINIMA + 1)
        self.assertEqual(servidor.objectos[ref.key][0], dados)

    def test_tres_partes_com_blocos_que_nao_coincidem_com_as_partes(self) -> None:
        alvo, servidor, _ = montar_s3_em_memoria(tamanho_da_parte=PARTE_MINIMA)
        dados = os.urandom(2 * PARTE_MINIMA + 12345)
        blocos = (dados[i : i + 1_000_003] for i in range(0, len(dados), 1_000_003))
        ref = alvo.storage.put(CTX, nova_chave(CTX, "audio"), blocos, META)
        self.assertEqual(
            metodos(servidor),
            ["POST uploads", "PUT parte 1", "PUT parte 2", "PUT parte 3", "POST envio"],
        )
        self.assertEqual(
            [len(p.corpo or b"") for p in servidor.pedidos[1:4]],
            [PARTE_MINIMA, PARTE_MINIMA, 12345],
        )
        guardado, cabecalhos = servidor.objectos[ref.key]
        self.assertEqual(guardado, dados)
        # Os metadados vao na abertura do envio, e ficam no objecto.
        self.assertEqual(cabecalhos["x-amz-meta-classe"], "audio")
        self.assertEqual(cabecalhos["x-amz-meta-retain-until"], "2026-10-13T08:30:00.000Z")
        self.assertEqual(cabecalhos["content-type"], "audio/ogg")

    def test_um_envio_que_falha_a_meio_e_abortado_e_sobe_o_erro_original(self) -> None:
        alvo, servidor, _ = montar_s3_em_memoria(tamanho_da_parte=PARTE_MINIMA)
        servidor.interceptar = lambda p: (
            resposta(500, erro_xml("InternalError")) if parametro(p, "partNumber") == "2" else None
        )
        with self.assertRaises(ArmazenamentoIndisponivelError) as apanhado:
            alvo.storage.put(CTX, nova_chave(CTX, "audio"), os.urandom(PARTE_MINIMA + 10), META)
        self.assertEqual(
            (apanhado.exception.operacao, apanhado.exception.estado, apanhado.exception.codigo),
            ("put", 500, "InternalError"),
        )
        self.assertEqual(
            metodos(servidor), ["POST uploads", "PUT parte 1", "PUT parte 2", "DELETE envio"]
        )
        self.assertEqual(servidor.envios, {}, "o envio nao ficou aberto")
        self.assertEqual(servidor.objectos, {}, "nada ficou escrito")

    def test_se_ate_o_aborto_falhar_o_erro_que_sobe_continua_a_ser_o_original(self) -> None:
        alvo, servidor, _ = montar_s3_em_memoria(tamanho_da_parte=PARTE_MINIMA)

        def interceptar(p: PedidoHttp) -> RespostaHttp | None:
            if parametro(p, "partNumber") == "1":
                return resposta(503, erro_xml("SlowDown"))
            if p.metodo == "DELETE":
                raise OSError("rede em baixo")
            return None

        servidor.interceptar = interceptar
        with self.assertRaises(ArmazenamentoIndisponivelError) as apanhado:
            alvo.storage.put(CTX, nova_chave(CTX, "audio"), os.urandom(PARTE_MINIMA + 10), META)
        self.assertEqual(apanhado.exception.codigo, "SlowDown")

    def test_um_fluxo_que_rebenta_a_meio_tambem_aborta_o_envio(self) -> None:
        alvo, servidor, _ = montar_s3_em_memoria(tamanho_da_parte=PARTE_MINIMA)

        def fluxo():  # noqa: ANN202
            yield os.urandom(PARTE_MINIMA + 10)
            raise RuntimeError("a origem dos bytes falhou")

        with self.assertRaisesRegex(RuntimeError, "a origem dos bytes falhou"):
            alvo.storage.put(CTX, nova_chave(CTX, "audio"), fluxo(), META)
        self.assertEqual(metodos(servidor), ["POST uploads", "PUT parte 1", "DELETE envio"])
        self.assertEqual(servidor.objectos, {})

    def test_respostas_incompletas_do_servidor_sao_erro_nao_sucesso(self) -> None:
        dados = os.urandom(PARTE_MINIMA + 10)
        casos = (
            (
                "abertura sem UploadId",
                lambda p: resposta(200, "<Resultado/>") if parametro(p, "uploads") is not None else None,
                "SemUploadId",
            ),
            (
                "parte sem ETag",
                lambda p: resposta(200) if parametro(p, "partNumber") is not None else None,
                "SemETag",
            ),
            (
                "fecho com 200 e erro no corpo",
                lambda p: (
                    resposta(200, erro_xml("InternalError"))
                    if p.metodo == "POST" and parametro(p, "uploadId") is not None
                    else None
                ),
                "InternalError",
            ),
        )
        for nome, interceptar, codigo in casos:
            with self.subTest(nome):
                alvo, servidor, _ = montar_s3_em_memoria(tamanho_da_parte=PARTE_MINIMA)
                servidor.interceptar = interceptar
                with self.assertRaises(ArmazenamentoIndisponivelError) as apanhado:
                    alvo.storage.put(CTX, nova_chave(CTX, "audio"), dados, META)
                self.assertEqual(apanhado.exception.codigo, codigo)
                self.assertEqual(servidor.objectos, {})

    def test_uma_parte_abaixo_de_5_mib_nao_se_configura(self) -> None:
        for tamanho in (PARTE_MINIMA - 1, 0, 1.5 * PARTE_MINIMA, float("nan"), True, "16"):
            with self.subTest(tamanho=tamanho), self.assertRaises(ValueError):
                montar_s3_em_memoria(tamanho_da_parte=tamanho)  # type: ignore[arg-type]


class Listagem(unittest.TestCase):
    def test_a_listagem_segue_as_paginas_ate_ao_fim(self) -> None:
        alvo, servidor, _ = montar_s3_em_memoria(pagina=2)
        refs = [
            alvo.storage.put(CTX, nova_chave(CTX, "audio"), os.urandom(i + 1), META)
            for i in range(5)
        ]
        servidor.pedidos.clear()
        base = prefixo_do_tenant(CTX)
        lista = alvo.storage.list(CTX, base)
        self.assertEqual([r.key for r in lista], sorted(r.key for r in refs))
        self.assertEqual(len(servidor.pedidos), 3, "5 chaves em paginas de 2 sao 3 pedidos")
        self.assertEqual(parametro(servidor.pedidos[0], "prefix"), base)
        self.assertIsNotNone(parametro(servidor.pedidos[1], "continuation-token"))

        # O limite tambem se respeita atraves das paginas.
        for limite in (4, 3):
            with self.assertRaises(ListagemTruncadaError):
                alvo.storage.list(CTX, base, limite=limite)
        self.assertEqual(len(alvo.storage.list(CTX, base, limite=5)), 5)

    def test_uma_listagem_ilegivel_e_erro_nao_meia_listagem(self) -> None:
        chave = f"t/{CTX.tenant_id}/audio/x"
        casos = (
            (
                "truncada sem continuacao",
                "<ListBucketResult><IsTruncated>true</IsTruncated><Contents>"
                f"<Key>{chave}</Key><Size>1</Size></Contents></ListBucketResult>",
                "SemContinuacao",
            ),
            (
                "entrada sem tamanho",
                "<ListBucketResult><IsTruncated>false</IsTruncated><Contents>"
                f"<Key>{chave}</Key></Contents></ListBucketResult>",
                "ListagemIlegivel",
            ),
            (
                "tamanho que nao e numero",
                "<ListBucketResult><IsTruncated>false</IsTruncated><Contents>"
                f"<Key>{chave}</Key><Size>-1</Size></Contents></ListBucketResult>",
                "ListagemIlegivel",
            ),
            (
                "entrada sem chave",
                "<ListBucketResult><IsTruncated>false</IsTruncated><Contents>"
                "<Size>1</Size></Contents></ListBucketResult>",
                "ListagemIlegivel",
            ),
        )
        for nome, xml, codigo in casos:
            with self.subTest(nome):
                alvo, servidor, _ = montar_s3_em_memoria()
                servidor.interceptar = lambda _p, xml=xml: resposta(200, xml)
                with self.assertRaises(ArmazenamentoIndisponivelError) as apanhado:
                    alvo.storage.list(CTX, prefixo_do_tenant(CTX))
                self.assertEqual(apanhado.exception.codigo, codigo)

    def test_xml_entidades_e_elementos(self) -> None:
        self.assertEqual(
            desescapar_xml("a&amp;b&lt;c&gt;d&quot;e&apos;f&#47;g&#x2F;h&desconhecida;"),
            "a&b<c>d\"e'f/g/h&desconhecida;",
        )
        self.assertEqual(elemento_xml("<A><Code>NoSuchKey</Code></A>", "Code"), "NoSuchKey")
        self.assertIsNone(elemento_xml("<A/>", "Code"))


class Erros(unittest.TestCase):
    def test_404_num_objecto_e_inexistente_404_num_bucket_e_configuracao_errada(self) -> None:
        alvo, servidor, _ = montar_s3_em_memoria()
        ref = ObjectRef(nova_chave(CTX, "audio"), 0)
        with self.assertRaises(ObjectoInexistenteError):
            alvo.storage.get(CTX, ref)
        with self.assertRaises(ObjectoInexistenteError):
            alvo.storage.head(CTX, ref)

        servidor.interceptar = lambda _p: resposta(404, erro_xml("NoSuchBucket"))
        for operacao in (
            lambda: alvo.storage.get(CTX, ref),
            lambda: alvo.storage.delete(CTX, ref),
            lambda: alvo.storage.list(CTX, prefixo_do_tenant(CTX)),
            lambda: alvo.storage.put(CTX, ref.key, b"x", META),
        ):
            with self.assertRaises(ArmazenamentoIndisponivelError) as apanhado:
                operacao()
            self.assertEqual(
                (apanhado.exception.estado, apanhado.exception.codigo), (404, "NoSuchBucket")
            )

    def test_apagar_o_que_o_servidor_diz_nao_existir_nao_e_erro(self) -> None:
        # Ha servidores que respondem 404 a um DELETE de chave inexistente, em
        # vez do 204 do S3. A porta promete idempotencia nos dois casos.
        alvo, servidor, _ = montar_s3_em_memoria()
        ref = ObjectRef(nova_chave(CTX, "audio"), 0)
        servidor.interceptar = lambda _p: resposta(404, erro_xml("NoSuchKey"))
        alvo.storage.delete(CTX, ref)
        self.assertEqual([p.metodo for p in servidor.pedidos], ["DELETE"])

    def test_um_erro_leva_estado_e_codigo_e_nunca_a_url_nem_as_credenciais(self) -> None:
        alvo, servidor, _ = montar_s3_em_memoria()
        ref = alvo.storage.put(CTX, nova_chave(CTX, "audio"), b"1234", META)
        fugas = (
            CREDENCIAIS_DE_TESTE.secret_access_key,
            CREDENCIAIS_DE_TESTE.access_key_id,
            "Signature=",
            CONFIG_DE_TESTE.endpoint,
            ref.key,
        )

        def conferir(operacao, estado: int | None, codigo: str | None) -> None:  # noqa: ANN001
            with self.assertRaises(ArmazenamentoIndisponivelError) as apanhado:
                operacao()
            erro = apanhado.exception
            self.assertEqual((erro.estado, erro.codigo), (estado, codigo))
            visivel = f"{erro}\n{erro!r}\n{erro.__cause__!r}\n{erro.args!r}"
            for fuga in fugas:
                self.assertNotIn(fuga, visivel)
            # A causa nao fica pendurada no erro: e nela que a URL viajava.
            self.assertIsNone(erro.__cause__)
            self.assertIsNone(erro.__context__)

        servidor.interceptar = lambda _p: resposta(
            500, erro_xml("InternalError") + CREDENCIAIS_DE_TESTE.secret_access_key
        )
        conferir(lambda: alvo.storage.get(CTX, ref), 500, "InternalError")

        servidor.interceptar = lambda _p: resposta(403, "isto nao e XML")
        conferir(lambda: alvo.storage.head(CTX, ref), 403, None)

        # Uma falha de rede traz, tipicamente, a URL na mensagem. Nao sobe.
        def rede_em_baixo(p: PedidoHttp) -> RespostaHttp | None:
            raise OSError(f"connect ECONNREFUSED {p.url} {p.cabecalhos['authorization']}")

        servidor.interceptar = rede_em_baixo
        conferir(lambda: alvo.storage.get(CTX, ref), None, None)
        conferir(lambda: alvo.storage.delete(CTX, ref), None, None)
        conferir(lambda: alvo.storage.list(CTX, prefixo_do_tenant(CTX)), None, None)

    def test_head_sem_content_length_nao_inventa_um_tamanho(self) -> None:
        alvo, servidor, _ = montar_s3_em_memoria()
        ref = ObjectRef(nova_chave(CTX, "audio"), 0)
        for cabecalhos in ({"x-amz-meta-classe": "audio"}, {"content-length": "-1"}, {"content-length": "muito"}):
            servidor.interceptar = lambda _p, c=cabecalhos: resposta(200, "", c)
            with self.assertRaises(ArmazenamentoIndisponivelError) as apanhado:
                alvo.storage.head(CTX, ref)
            self.assertEqual(apanhado.exception.codigo, "SemContentLength")

    def test_o_repr_das_credenciais_nao_mostra_nada(self) -> None:
        texto = f"{CREDENCIAIS_DE_TESTE!r} {CREDENCIAIS_DE_TESTE}"
        self.assertNotIn(CREDENCIAIS_DE_TESTE.secret_access_key, texto)
        self.assertNotIn(CREDENCIAIS_DE_TESTE.access_key_id, texto)


class Assinatura(unittest.TestCase):
    def test_todos_os_pedidos_vao_assinados_com_os_metadados_na_assinatura(self) -> None:
        alvo, servidor, _ = montar_s3_em_memoria()
        ref = alvo.storage.put(CTX, nova_chave(CTX, "audio"), b"1234", META)
        alvo.storage.head(CTX, ref)
        alvo.storage.list(CTX, prefixo_do_tenant(CTX))
        alvo.storage.delete(CTX, ref)
        self.assertEqual(len(servidor.pedidos), 4)
        for pedido in servidor.pedidos:
            autorizacao = pedido.cabecalhos["authorization"]
            self.assertRegex(
                autorizacao,
                r"^AWS4-HMAC-SHA256 Credential=chave-de-teste/20261012/ao-teste-1/s3/aws4_request, ",
            )
            self.assertNotIn(CREDENCIAIS_DE_TESTE.secret_access_key, autorizacao)
            self.assertNotIn("host", pedido.cabecalhos, "o Host e do cliente HTTP")
            self.assertTrue(
                pedido.url.startswith(f"{CONFIG_DE_TESTE.endpoint}/{CONFIG_DE_TESTE.bucket}")
            )
        self.assertIn(
            "SignedHeaders=content-type;host;x-amz-content-sha256;x-amz-date;"
            "x-amz-meta-classe;x-amz-meta-retain-until,",
            servidor.pedidos[0].cabecalhos["authorization"],
        )

    def test_um_pedido_adulterado_depois_de_assinado_e_recusado_pelo_servidor_de_teste(self) -> None:
        # Prova que o servidor em memoria confere mesmo: sem isto, a bateria
        # "s3 em memoria" passava com uma assinatura qualquer.
        _, servidor, _ = montar_s3_em_memoria()

        def motor(transporte, credenciais: Credenciais = CREDENCIAIS_DE_TESTE) -> MotorS3:  # noqa: ANN001
            return MotorS3(
                endpoint=CONFIG_DE_TESTE.endpoint,
                bucket=CONFIG_DE_TESTE.bucket,
                regiao=CONFIG_DE_TESTE.regiao,
                credenciais=lambda: credenciais,
                transporte=transporte,
                agora=lambda: AGORA,
            )

        def adulterar(mudar):  # noqa: ANN001, ANN202
            return motor(lambda p: servidor.transporte(mudar(p)))

        chave = nova_chave(CTX, "audio")
        meta = MetaBruta("audio/ogg", {"classe": "audio", "retain-until": "2026-10-13T08:30:00.000Z"})
        motor(servidor.transporte).put(chave, (b"1234",), meta)

        def recusado(operacao) -> None:  # noqa: ANN001
            with self.assertRaises(ArmazenamentoIndisponivelError) as apanhado:
                operacao()
            self.assertIn(apanhado.exception.estado, (400, 403))

        recusado(
            lambda: adulterar(
                lambda p: PedidoHttp(p.metodo, p.url, {**p.cabecalhos, "x-amz-meta-classe": "imagem"}, p.corpo)
            ).put(chave, (b"1234",), meta)
        )
        recusado(
            lambda: adulterar(lambda p: PedidoHttp(p.metodo, p.url, p.cabecalhos, b"12345")).put(
                chave, (b"1234",), meta
            )
        )
        recusado(
            lambda: adulterar(
                lambda p: PedidoHttp(p.metodo, p.url.replace("/audio/", "/imagem/"), p.cabecalhos, p.corpo)
            ).get(chave)
        )
        recusado(
            lambda: adulterar(
                lambda p: PedidoHttp(p.metodo, p.url, {**p.cabecalhos, "authorization": ""}, p.corpo)
            ).get(chave)
        )
        recusado(
            lambda: motor(
                servidor.transporte, Credenciais(CREDENCIAIS_DE_TESTE.access_key_id, "valor-errado")
            ).get(chave)
        )
        recusado(
            lambda: motor(
                servidor.transporte, Credenciais("outra-chave", CREDENCIAIS_DE_TESTE.secret_access_key)
            ).get(chave)
        )
        # E o pedido honesto continua a passar.
        self.assertEqual(b"".join(motor(servidor.transporte).get(chave)), b"1234")

    def test_a_assinatura_e_determinista_e_sensivel_a_cada_parte_do_pedido(self) -> None:
        base = {
            "metodo": "GET",
            "url": "http://s3.teste.invalid:8333/kamba-teste/t/x?list-type=2&prefix=t%2Fx%2F",
            "cabecalhos": {"host": "s3.teste.invalid:8333", "x-amz-date": "20261012T090000Z"},
            "hash_do_corpo": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            "regiao": "ao-teste-1",
            "quando": "20261012T090000Z",
            "segredo": "valor-de-teste",
        }
        referencia, assinados = assinatura(**base)
        self.assertRegex(referencia, r"^[0-9a-f]{64}$")
        self.assertEqual(assinados, "host;x-amz-date")
        self.assertEqual(assinatura(**base), (referencia, assinados))
        self.assertEqual(referencia, VECTOR_PARTILHADO)

        variantes = [
            assinatura(**{**base, "metodo": "HEAD"})[0],
            assinatura(**{**base, "url": base["url"].replace("/t/x", "/t/y")})[0],
            assinatura(**{**base, "url": base["url"].replace("list-type=2", "list-type=1")})[0],
            assinatura(**{**base, "cabecalhos": {**base["cabecalhos"], "host": "outro:8333"}})[0],
            assinatura(**{**base, "hash_do_corpo": "UNSIGNED-PAYLOAD"})[0],
            assinatura(**{**base, "regiao": "us-east-1"})[0],
            assinatura(**{**base, "quando": "20261012T090001Z"})[0],
            assinatura(**{**base, "quando": "20261013T090000Z"})[0],
            assinatura(**{**base, "segredo": "valor-de-testf"})[0],
        ]
        self.assertEqual(len({referencia, *variantes}), len(variantes) + 1)

    def test_canonicalizacao(self) -> None:
        self.assertEqual(codificar("a b/c~d-e_f.g!'()*é"), "a%20b%2Fc~d-e_f.g%21%27%28%29%2A%C3%A9")
        self.assertEqual(caminho_canonico("/kamba-teste/t/a b/c%20d"), "/kamba-teste/t/a%20b/c%20d")
        self.assertEqual(
            query_canonica(
                [("prefix", "t/x/"), ("list-type", "2"), ("a", "2"), ("a", "1"), ("uploads", "")]
            ),
            "a=1&a=2&list-type=2&prefix=t%2Fx%2F&uploads=",
        )
        self.assertEqual(data_amz(datetime(2026, 10, 12, 9, 5, 7, 891000, tzinfo=UTC)), "20261012T090507Z")
        self.assertEqual(anfitriao("http://s3.teste.invalid:8333/x"), "s3.teste.invalid:8333")
        self.assertEqual(anfitriao("http://s3.teste.invalid:80/x"), "s3.teste.invalid")
        self.assertEqual(anfitriao("https://s3.teste.invalid:443"), "s3.teste.invalid")
        self.assertEqual(anfitriao("https://s3.teste.invalid:8443"), "s3.teste.invalid:8443")
        self.assertEqual(anfitriao("http://[::1]:8333/x"), "[::1]:8333")

    def test_assinar_pedido_e_presignar_get(self) -> None:
        cabecalhos = assinar_pedido(
            metodo="PUT",
            url="http://s3.teste.invalid:8333/kamba-teste/t/x",
            cabecalhos={"Content-Type": "audio/ogg", "X-Amz-Meta-Classe": "audio"},
            corpo=b"abc",
            credenciais=CREDENCIAIS_DE_TESTE,
            regiao="ao-teste-1",
            agora=AGORA,
        )
        self.assertEqual(
            sorted(cabecalhos),
            ["authorization", "content-type", "host", "x-amz-content-sha256", "x-amz-date", "x-amz-meta-classe"],
        )
        self.assertEqual(
            cabecalhos["x-amz-content-sha256"],
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
        )
        self.assertEqual(cabecalhos["host"], "s3.teste.invalid:8333")

        url = presignar_get(
            url="http://s3.teste.invalid:8333/kamba-teste/t/x",
            credenciais=CREDENCIAIS_DE_TESTE,
            regiao="ao-teste-1",
            agora=AGORA,
            expira_s=60,
        )
        partes = urlsplit(url)
        q = {n: v[0] for n, v in parse_qs(partes.query).items()}
        self.assertEqual(f"{partes.scheme}://{partes.netloc}{partes.path}", "http://s3.teste.invalid:8333/kamba-teste/t/x")
        self.assertEqual(q["X-Amz-Expires"], "60")
        self.assertEqual(q["X-Amz-Date"], "20261012T090000Z")
        self.assertEqual(q["X-Amz-SignedHeaders"], "host")
        self.assertEqual(q["X-Amz-Algorithm"], "AWS4-HMAC-SHA256")
        self.assertRegex(q["X-Amz-Signature"], r"^[0-9a-f]{64}$")
        self.assertNotIn(CREDENCIAIS_DE_TESTE.secret_access_key, url)
        # A mesma URL do lado TypeScript: as duas implementacoes assinam igual.
        self.assertEqual(q["X-Amz-Signature"], URL_PARTILHADA)


#: Assinatura da URL pre-assinada acima, igual em `storage.s3.test.ts`.
URL_PARTILHADA = "d7afce495852f7aca64e58187e49aabc92528e6808b5b71db9d3463c0302eccd"


class _Servidor(http.server.BaseHTTPRequestHandler):
    vistos: list[tuple[str, str, str | None, bytes]] = []

    def _tratar(self) -> None:
        corpo = self.rfile.read(int(self.headers.get("content-length") or 0))
        type(self).vistos.append(
            (self.command, self.path, self.headers.get("x-amz-meta-classe"), corpo)
        )
        if self.path == "/redireccionar":
            self.send_response(307)
            self.send_header("location", "/outro-sitio")
            self.send_header("content-length", "0")
            self.end_headers()
        elif self.command == "HEAD":
            self.send_response(200)
            self.send_header("X-Amz-Meta-Classe", "audio")
            self.send_header("content-length", "0")
            self.end_headers()
        else:
            self.send_response(200)
            self.send_header("ETag", '"abc"')
            self.send_header("content-length", "4")
            self.end_headers()
            self.wfile.write("olá".encode())

    do_GET = do_PUT = do_HEAD = _tratar  # noqa: N815

    def log_message(self, *_args: object) -> None:
        pass


class TransportePorHttp(unittest.TestCase):
    def test_entrega_metodo_cabecalhos_e_corpo_e_nao_segue_redireccionamentos(self) -> None:
        _Servidor.vistos = []
        servidor = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Servidor)
        fio = threading.Thread(target=servidor.serve_forever, daemon=True)
        fio.start()
        try:
            base = f"http://127.0.0.1:{servidor.server_address[1]}"
            transporte = transporte_por_http(5)

            escrita = transporte(
                PedidoHttp("PUT", f"{base}/b/chave?x=1", {"x-amz-meta-classe": "audio"}, "conteúdo".encode())
            )
            self.assertEqual(escrita.estado, 200)
            self.assertEqual(escrita.cabecalhos["etag"], '"abc"', "nomes em minusculas")
            self.assertEqual(b"".join(escrita.corpo).decode(), "olá")

            cabeca = transporte(PedidoHttp("HEAD", f"{base}/b/chave", {}))
            self.assertEqual(cabeca.cabecalhos["x-amz-meta-classe"], "audio")
            self.assertEqual(b"".join(cabeca.corpo), b"")

            redireccionado = transporte(PedidoHttp("GET", f"{base}/redireccionar", {}))
            self.assertEqual(redireccionado.estado, 307, "o pedido assinado nao segue para outro sitio")
            self.assertEqual(b"".join(redireccionado.corpo), b"")

            self.assertEqual(
                _Servidor.vistos,
                [
                    ("PUT", "/b/chave?x=1", "audio", "conteúdo".encode()),
                    ("HEAD", "/b/chave", None, b""),
                    ("GET", "/redireccionar", None, b""),
                ],
            )
        finally:
            servidor.shutdown()
            servidor.server_close()
            fio.join(5)

    def test_uma_ligacao_recusada_e_um_erro_de_rede_que_o_motor_traduz(self) -> None:
        # Uma porta em que ninguem escuta.
        import socket

        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            porta = s.getsockname()[1]
        motor = MotorS3(
            endpoint=f"http://127.0.0.1:{porta}",
            bucket="kamba-teste",
            regiao="ao-teste-1",
            credenciais=lambda: CREDENCIAIS_DE_TESTE,
            tempo_limite_s=2,
        )
        with self.assertRaises(ArmazenamentoIndisponivelError) as apanhado:
            motor.get(f"t/{CTX.tenant_id}/audio/x")
        self.assertIsNone(apanhado.exception.estado)
        self.assertNotIn(str(porta), str(apanhado.exception))


if __name__ == "__main__":
    unittest.main()
