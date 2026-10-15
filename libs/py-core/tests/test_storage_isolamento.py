"""Isolamento por tenant no armazenamento: chaves, prefixos e recusas (KAM-011).

A bateria de contrato ja tem o X-08 visto de fora — A contra B, nos alvos todos.
Esta suite ataca o mesmo por dentro, onde as arestas estao:

1. **a forma da chave**: tudo o que nao e exactamente
   `t/{tenant_id}/{classe}/{aaaa}/{mm}/{uuid}` e recusado;
2. **o dono da chave**: a recusa acontece **antes** de o motor ser tocado —
   conta-se, nao se presume;
3. **o prefixo de listagem**;
4. **a segunda camada**: um motor que mente (devolve chaves de outro tenant)
   nao consegue fazer a porta devolve-las.

Cada caso de recusa confere a **classe** do erro e que o motor ficou intocado.
Espelho de `packages/core-ts/tests/storage.isolamento.test.ts`, com os casos
que so existem em Python (`\\n` final, `bool` por `int`, digitos Unicode).
"""

from __future__ import annotations

import unittest
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime, timedelta, timezone

from kamba_core.storage import (
    ChaveForaDoTenantError,
    ChaveInvalidaError,
    Ctx,
    CtxEmFaltaError,
    MetaInvalidaError,
    ObjectMeta,
    ObjectRef,
    RespostaDoMotorInvalidaError,
    TenantInvalidoError,
    nova_chave,
    partes_da_chave,
    prefixo_do_tenant,
)
from kamba_core.storage.chave import chave_do_ctx, prefixo_do_ctx, tenant_do_ctx
from kamba_core.storage.guarda import ArmazenamentoPorTenant
from kamba_core.storage.motor import Escrito, InfoBruta, ItemListado, Listagem, MetaBruta

# Com letras, de proposito: `A.upper()` tem de ser diferente de `A`.
A = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"
B = "bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb"
ID = "cccccccc-3333-4333-8333-cccccccccccc"
CTX_A = Ctx(A)
CTX_B = Ctx(B)

PRAZO = datetime(2026, 10, 13, 8, 30, tzinfo=UTC)
PRAZO_TEXTO = "2026-10-13T08:30:00.000Z"
META = ObjectMeta("audio/ogg", "audio", PRAZO)


class MotorEspiao:
    """Um motor que so regista o que lhe pedem, e devolve o que lhe mandarem."""

    nome = "espiao"

    def __init__(self) -> None:
        self.chamadas: list[str] = []
        self.listagem: tuple[ItemListado, ...] = ()
        self.truncada = False
        self.info = InfoBruta(3, "audio/ogg", {"classe": "audio", "retain-until": PRAZO_TEXTO})
        self.meta: MetaBruta | None = None

    def put(self, chave: str, corpo: Iterable[bytes], meta: MetaBruta) -> Escrito:
        self.chamadas.append(f"put {chave}")
        self.meta = meta
        return Escrito(sum(len(b) for b in corpo), "0" * 64)

    def get(self, chave: str) -> Iterator[bytes]:
        self.chamadas.append(f"get {chave}")
        return iter(())

    def head(self, chave: str) -> InfoBruta:
        self.chamadas.append(f"head {chave}")
        return self.info

    def delete(self, chave: str) -> None:
        self.chamadas.append(f"delete {chave}")

    def list(self, prefixo: str, maximo: int) -> Listagem:
        self.chamadas.append(f"list {prefixo} {maximo}")
        return Listagem(self.listagem, self.truncada)

    def sign_url(self, chave: str, ttl_segundos: int) -> str:
        self.chamadas.append(f"sign_url {chave} {ttl_segundos}")
        return f"http://exemplo.invalid/{chave}"


def montar() -> tuple[MotorEspiao, ArmazenamentoPorTenant]:
    motor = MotorEspiao()
    return motor, ArmazenamentoPorTenant(motor)


def chave_de(tenant: str, classe: str = "audio") -> str:
    return f"t/{tenant}/{classe}/2026/10/{ID}"


def ref(key: object) -> ObjectRef:
    return ObjectRef(key, 3)  # type: ignore[arg-type]


#: Tentativas de sair do prefixo. Todas comecam por algo que parece do tenant A
#: ou que um servidor permissivo podia normalizar para outro sitio.
MAL_FORMADAS = (
    "",
    "t",
    "t/",
    f"t/{A}",
    f"t/{A}/",
    f"t/{A}/audio/2026/10",
    f"t/{A}/audio/2026/10/",
    f"t/{A}/audio/2026/10/{ID}/",
    f"t/{A}/audio/2026/10/{ID}/extra",
    f"/t/{A}/audio/2026/10/{ID}",
    f"t//{A}/audio/2026/10/{ID}",
    f"t/{A}//audio/2026/10/{ID}",
    f"t/{A}/audio/2026/10/../../../../{B}/audio/2026/10/{ID}",
    f"t/{A}/../{B}/audio/2026/10/{ID}",
    f"t/{A}/audio/../../{B}/2026/10/{ID}",
    f"t/{A}/audio/2026/10/..",
    f"t/{A}/audio/2026/10/%2e%2e",
    f"t/{A}%2faudio/2026/10/{ID}",
    f"t/{A}/audio/2026/10/{ID}%00",
    f"t/{A}/audio/2026/10/{ID}\x00",
    # So em Python: `$` casa antes de um `\n` final. Tem de ser `fullmatch`.
    f"t/{A}/audio/2026/10/{ID}\n",
    f"t/{A}/audio/2026/10/{ID}\r\n",
    f"t/{A}/audio/2026/10/{ID} ",
    f" t/{A}/audio/2026/10/{ID}",
    f"t/{A}/audio/2026/10/{ID}?versionId=1",
    f"t/{A}/audio/2026/10/{ID}#x",
    f"T/{A}/audio/2026/10/{ID}",
    f"t/{A.upper()}/audio/2026/10/{ID}",
    f"t/{A}/AUDIO/2026/10/{ID}",
    f"t/{A}/audio/2026/10/{ID.upper()}",
    f"t/{A}/audio/2026/13/{ID}",
    f"t/{A}/audio/2026/00/{ID}",
    f"t/{A}/audio/2026/1/{ID}",
    f"t/{A}/audio/26/10/{ID}",
    # So em Python: `\d` casa digitos de outros alfabetos. As classes sao `[0-9]`.
    f"t/{A}/audio/２０２６/10/{ID}",
    f"t/{A}/audio/2026/١٠/{ID}",
    f"t/{A}/audio/2026/10/nao-e-um-uuid",
    f"t/{A.replace('-', '')}/audio/2026/10/{ID}",
    f"t/{A}/a/2026/10/{ID}",
    f"t/{A}/{'a' * 33}/2026/10/{ID}",
    f"t/{A}/media/audio/2026/10/{ID}",
    f"t\\{A}\\audio\\2026\\10\\{ID}",
    f"x/{A}/audio/2026/10/{ID}",
    f"t/*/audio/2026/10/{ID}",
)


class AForma(unittest.TestCase):
    def test_nova_chave_cunha_a_forma_canonica_com_ano_e_mes_em_utc(self) -> None:
        key = nova_chave(CTX_A, "audio", datetime(2026, 12, 31, 23, 30, tzinfo=UTC))
        self.assertRegex(key, rf"^t/{A}/audio/2026/12/[0-9a-f-]{{36}}$")
        partes = partes_da_chave(key)
        self.assertEqual(
            (partes.tenant_id, partes.classe, partes.ano, partes.mes),
            (A, "audio", "2026", "12"),
        )
        # 00:30 de 1 de Janeiro em Luanda (UTC+1) ainda e Dezembro em UTC.
        luanda = timezone(timedelta(hours=1))
        self.assertIn("/2026/12/", nova_chave(CTX_A, "audio", datetime(2027, 1, 1, 0, 30, tzinfo=luanda)))
        self.assertIn(
            "/kyc_documento/2026/03/",
            nova_chave(CTX_A, "kyc_documento", datetime(2026, 3, 5, 12, tzinfo=UTC)),
        )
        # Sem instante dado, usa o de agora.
        self.assertRegex(nova_chave(CTX_A, "audio"), rf"^t/{A}/audio/[0-9]{{4}}/[0-9]{{2}}/")

    def test_nova_chave_nao_repete_e_nao_aceita_classe_nem_data_invalidas(self) -> None:
        self.assertEqual(len({nova_chave(CTX_A, "audio") for _ in range(200)}), 200)
        for classe in ("", "A", "a", "Audio", "áudio", "au dio", "au/dio", "..", "a" * 33, "1audio", "audio\n", 7, None):
            with self.subTest(classe=classe), self.assertRaises(MetaInvalidaError):
                nova_chave(CTX_A, classe)  # type: ignore[arg-type]
        for agora in (datetime(2026, 10, 12, 9, 0), "2026-10-12", 0):
            with self.subTest(agora=agora), self.assertRaises(ChaveInvalidaError):
                nova_chave(CTX_A, "audio", agora)  # type: ignore[arg-type]
        with self.assertRaises(CtxEmFaltaError):
            nova_chave(Ctx(""), "audio")

    def test_uma_chave_que_nao_e_a_forma_canonica_e_recusada_em_todas_as_operacoes(self) -> None:
        for key in MAL_FORMADAS:
            with self.subTest(key=key):
                motor, storage = montar()
                with self.assertRaises(ChaveInvalidaError):
                    partes_da_chave(key)
                with self.assertRaises(ChaveInvalidaError):
                    storage.put(CTX_A, key, b"x", META)
                with self.assertRaises(ChaveInvalidaError):
                    storage.get(CTX_A, ref(key))
                with self.assertRaises(ChaveInvalidaError):
                    storage.head(CTX_A, ref(key))
                with self.assertRaises(ChaveInvalidaError):
                    storage.sign_url(CTX_A, ref(key), ttl_seconds=60)
                with self.assertRaises(ChaveInvalidaError):
                    storage.delete(CTX_A, ref(key))
                self.assertEqual(motor.chamadas, [], "o motor nao foi tocado")

    def test_o_que_nao_e_texto_nao_e_chave(self) -> None:
        motor, storage = montar()

        class ComStr:
            def __str__(self) -> str:
                return chave_de(A)

        for key in (None, 7, {}, [], [chave_de(A)], chave_de(A).encode(), ComStr()):
            with self.subTest(key=key):
                with self.assertRaises(ChaveInvalidaError):
                    storage.get(CTX_A, ref(key))
                with self.assertRaises(ChaveInvalidaError):
                    storage.put(CTX_A, key, b"x", META)  # type: ignore[arg-type]
        for referencia in (None, "t/…", 7, {"key": chave_de(A)}):
            with self.subTest(referencia=referencia):
                with self.assertRaises(ChaveInvalidaError):
                    storage.get(CTX_A, referencia)  # type: ignore[arg-type]
                with self.assertRaises(ChaveInvalidaError):
                    storage.delete(CTX_A, referencia)  # type: ignore[arg-type]
        self.assertEqual(motor.chamadas, [])

    def test_a_mensagem_de_uma_chave_recusada_nao_repete_a_chave(self) -> None:
        engano = "valor-passado-por-engano-no-sitio-da-chave"
        for tentativa in (engano, f"t/{A}/audio/2026/10/{engano}"):
            with self.assertRaises(ChaveInvalidaError) as apanhado:
                partes_da_chave(tentativa)
            self.assertNotIn(engano, str(apanhado.exception))


class ODono(unittest.TestCase):
    def test_uma_chave_de_outro_tenant_e_recusada_antes_de_o_motor_ser_tocado(self) -> None:
        motor, storage = montar()
        de_b = chave_de(B)

        with self.assertRaises(ChaveForaDoTenantError):
            chave_do_ctx(CTX_A, de_b, "get")
        with self.assertRaises(ChaveForaDoTenantError):
            storage.put(CTX_A, de_b, b"x", META)
        with self.assertRaises(ChaveForaDoTenantError):
            storage.get(CTX_A, ref(de_b))
        with self.assertRaises(ChaveForaDoTenantError):
            storage.head(CTX_A, ref(de_b))
        with self.assertRaises(ChaveForaDoTenantError):
            storage.sign_url(CTX_A, ref(de_b), ttl_seconds=60)
        with self.assertRaises(ChaveForaDoTenantError):
            storage.delete(CTX_A, ref(de_b))
        self.assertEqual(motor.chamadas, [], "nenhuma das seis tentativas chegou ao motor")

        # A metade positiva, no mesmo motor: com o contexto certo, chega.
        storage.get(CTX_B, ref(de_b))
        storage.sign_url(CTX_B, ref(de_b), ttl_seconds=60)
        storage.delete(CTX_B, ref(de_b))
        storage.put(CTX_B, de_b, b"abc", META)
        self.assertEqual(
            motor.chamadas,
            [f"get {de_b}", f"sign_url {de_b} 60", f"delete {de_b}", f"put {de_b}"],
        )

    def test_a_recusa_nao_diz_de_quem_e_a_chave_nem_se_o_objecto_existe(self) -> None:
        _, storage = montar()
        for operacao in (
            lambda: storage.get(CTX_A, ref(chave_de(B))),
            lambda: storage.sign_url(CTX_A, ref(chave_de(B)), ttl_seconds=60),
            lambda: storage.list(CTX_A, prefixo_do_tenant(CTX_B)),
        ):
            with self.assertRaises(ChaveForaDoTenantError) as apanhado:
                operacao()
            self.assertNotIn(B, str(apanhado.exception))
            self.assertNotIn(ID, str(apanhado.exception))

    def test_dois_tenants_que_diferem_num_so_caracter_nao_se_confundem(self) -> None:
        quase = A[:-1] + "2"
        motor, storage = montar()
        with self.assertRaises(ChaveForaDoTenantError):
            storage.get(CTX_A, ref(chave_de(quase)))
        with self.assertRaises(ChaveForaDoTenantError):
            storage.list(CTX_A, f"t/{quase}/")
        self.assertEqual(motor.chamadas, [])

    def test_o_contexto_valida_se_primeiro_e_so_aceita_o_uuid_canonico_em_minusculas(self) -> None:
        motor, storage = montar()
        for ctx in (Ctx(None), Ctx(""), None, object()):  # type: ignore[arg-type]
            with self.subTest(ctx=ctx):
                with self.assertRaises(CtxEmFaltaError):
                    tenant_do_ctx(ctx)
                # Mesmo com uma chave que tambem e invalida, o erro e o do contexto.
                with self.assertRaises(CtxEmFaltaError):
                    storage.get(ctx, ref("lixo"))  # type: ignore[arg-type]
        for tenant in (
            A.upper(),
            A.replace("-", ""),
            f"{{{A}}}",
            f" {A}",
            f"{A}\n",
            f"{A}/",
            "*",
            "..",
            7,
            {},
            [A],
            A.encode(),
        ):
            with self.subTest(tenant=tenant):
                ctx = Ctx(tenant)  # type: ignore[arg-type]
                with self.assertRaises(TenantInvalidoError):
                    tenant_do_ctx(ctx)
                with self.assertRaises(TenantInvalidoError):
                    storage.get(ctx, ref(chave_de(A)))
                with self.assertRaises(TenantInvalidoError):
                    storage.list(ctx, f"t/{A}/")
        self.assertEqual(motor.chamadas, [])
        # A mensagem diz o tipo e o comprimento, nao o valor.
        with self.assertRaises(TenantInvalidoError) as apanhado:
            tenant_do_ctx(Ctx("valor-que-nao-devia-aparecer"))
        self.assertNotIn("valor-que-nao-devia-aparecer", str(apanhado.exception))


class OPrefixo(unittest.TestCase):
    def test_um_prefixo_tem_de_comecar_pelo_do_tenant_com_a_barra(self) -> None:
        motor, storage = montar()
        for prefixo in (
            "",
            "t",
            "t/",
            f"t/{A}",
            f"t/{A[:8]}",
            f"t/{B}/",
            f"t/{B}/audio/",
            f"/t/{A}/",
            f"T/{A}/",
            f"x/{A}/",
            f"t/{A.upper()}/",
        ):
            with self.subTest(prefixo=prefixo):
                with self.assertRaises(ChaveForaDoTenantError):
                    prefixo_do_ctx(CTX_A, prefixo)
                with self.assertRaises(ChaveForaDoTenantError):
                    storage.list(CTX_A, prefixo)
        for prefixo in (
            f"t/{A}/../{B}/",
            f"t/{A}/audio/../../{B}/",
            f"t/{A}//",
            f"t/{A}/audio//2026/",
            f"t/{A}/%2e%2e/",
            f"t/{A}/Audio/",
            f"t/{A}/audio/*",
            f"t/{A}/audio/ ",
            f"t/{A}/audio/\x00",
            f"t/{A}/audio/\n",
            f"t/{A}/{'a/' * 60}",
            None,
            7,
            {},
        ):
            with self.subTest(prefixo=prefixo):
                with self.assertRaises(ChaveInvalidaError):
                    prefixo_do_ctx(CTX_A, prefixo)
                with self.assertRaises(ChaveInvalidaError):
                    storage.list(CTX_A, prefixo)  # type: ignore[arg-type]
        self.assertEqual(motor.chamadas, [], "nenhum prefixo recusado chegou ao motor")

        for prefixo in (f"t/{A}/", f"t/{A}/audio/", f"t/{A}/audio/2026/", f"t/{A}/audio/2026/10/cccc", f"t/{A}/au"):
            self.assertEqual(prefixo_do_ctx(CTX_A, prefixo), prefixo)


class ASegundaCamada(unittest.TestCase):
    def test_um_motor_que_devolve_chaves_de_outro_tenant_nao_as_faz_chegar(self) -> None:
        motor, storage = montar()
        minha = chave_de(A)

        # Metade positiva: uma listagem honesta passa.
        motor.listagem = (ItemListado(minha, 3),)
        self.assertEqual(storage.list(CTX_A, f"t/{A}/"), [ObjectRef(minha, 3, None)])

        for intrusa in (
            chave_de(B),
            f"t/{B}/",
            f"t/{A[:-1]}2/audio/2026/10/{ID}",
            f"x{minha}",
            "",
            f"T/{A}/audio/2026/10/{ID}",
            7,
            None,
        ):
            with self.subTest(intrusa=intrusa):
                motor.listagem = (ItemListado(minha, 3), ItemListado(intrusa, 9))  # type: ignore[arg-type]
                # Falha inteira: nao devolve "as boas", porque isso esconderia o defeito.
                with self.assertRaises(RespostaDoMotorInvalidaError):
                    storage.list(CTX_A, f"t/{A}/")

        # Dentro do tenant mas fora do prefixo pedido tambem e uma resposta errada.
        motor.listagem = (ItemListado(chave_de(A, "imagem"), 1),)
        with self.assertRaises(RespostaDoMotorInvalidaError):
            storage.list(CTX_A, f"t/{A}/audio/")

    def test_head_recusa_metadados_que_nao_batem_com_a_chave_ou_nao_se_leem(self) -> None:
        motor, storage = montar()
        key = chave_de(A)

        info = storage.head(CTX_A, ref(key))
        self.assertEqual(info.classe, "audio")
        self.assertEqual(info.retain_until, PRAZO)

        for metadados in (
            {"classe": "imagem", "retain-until": PRAZO_TEXTO},
            {"retain-until": PRAZO_TEXTO},
            {"classe": "audio"},
            {"classe": "audio", "retain-until": "amanha"},
            {"classe": "audio", "retain-until": ""},
            {"classe": "audio", "retain-until": "2026-10-13"},
            {"classe": "audio", "retain-until": "2026-10-13T08:30:00"},
            {"classe": "audio", "retain-until": "2026-13-45T99:99:99Z"},
            {},
        ):
            with self.subTest(metadados=metadados):
                motor.info = InfoBruta(3, "audio/ogg", metadados)
                with self.assertRaises(RespostaDoMotorInvalidaError):
                    storage.head(CTX_A, ref(key))


class OsMetadadosNaEscrita(unittest.TestCase):
    def test_put_exige_classe_igual_a_da_chave_tipo_e_retain_until_validos(self) -> None:
        motor, storage = montar()
        key = chave_de(A)

        for meta in (
            ObjectMeta("audio/ogg", "imagem", PRAZO),
            ObjectMeta("audio/ogg", "Audio", PRAZO),
            ObjectMeta("audio/ogg", None, PRAZO),  # type: ignore[arg-type]
            ObjectMeta("", "audio", PRAZO),
            ObjectMeta("audio", "audio", PRAZO),
            ObjectMeta("audio/ogg\r\nx-amz-meta-classe: imagem", "audio", PRAZO),
            ObjectMeta("audio/ogg\nx-injectado: 1", "audio", PRAZO),
            ObjectMeta("audio/ogg\n", "audio", PRAZO),
            ObjectMeta(7, "audio", PRAZO),  # type: ignore[arg-type]
            ObjectMeta("audio/ogg", "audio", None),  # type: ignore[arg-type]
            ObjectMeta("audio/ogg", "audio", datetime(2026, 10, 13, 8, 30)),
            ObjectMeta("audio/ogg", "audio", "2026-10-13T08:30:00Z"),  # type: ignore[arg-type]
            ObjectMeta("audio/ogg", "audio", 1791880200),  # type: ignore[arg-type]
            None,
            "audio",
            {"content_type": "audio/ogg", "classe": "audio", "retain_until": PRAZO},
        ):
            with self.subTest(meta=meta), self.assertRaises(MetaInvalidaError):
                storage.put(CTX_A, key, b"abc", meta)  # type: ignore[arg-type]
        for corpo in ("texto", None, 7):
            with self.subTest(corpo=corpo), self.assertRaises(MetaInvalidaError):
                storage.put(CTX_A, key, corpo, META)  # type: ignore[arg-type]
        self.assertEqual(motor.chamadas, [], "nenhum put recusado chegou ao motor")

        escrito = storage.put(
            CTX_A, key, bytearray(b"abc"), ObjectMeta("audio/ogg; codecs=opus", "audio", PRAZO)
        )
        self.assertEqual(escrito, ObjectRef(key, 3, "0" * 64))
        assert motor.meta is not None
        self.assertEqual(
            dict(motor.meta.metadados), {"classe": "audio", "retain-until": PRAZO_TEXTO}
        )

    def test_retain_until_guarda_se_em_utc_venha_em_que_fuso_vier(self) -> None:
        motor, storage = montar()
        luanda = timezone(timedelta(hours=1))
        storage.put(
            CTX_A,
            chave_de(A),
            memoryview(b"abc"),
            ObjectMeta("audio/ogg", "audio", datetime(2026, 10, 13, 9, 30, 0, 123456, tzinfo=luanda)),
        )
        assert motor.meta is not None
        self.assertEqual(motor.meta.metadados["retain-until"], "2026-10-13T08:30:00.123Z")

    def test_list_valida_o_limite_e_passa_o_ao_motor(self) -> None:
        motor, storage = montar()
        for limite in (0, -1, 1.5, 10_001, float("nan"), "7", True):
            with self.subTest(limite=limite), self.assertRaises(MetaInvalidaError):
                storage.list(CTX_A, f"t/{A}/", limite=limite)  # type: ignore[arg-type]
        self.assertEqual(motor.chamadas, [])
        storage.list(CTX_A, f"t/{A}/")
        storage.list(CTX_A, f"t/{A}/", limite=7)
        self.assertEqual(motor.chamadas, [f"list t/{A}/ 1000", f"list t/{A}/ 7"])

    def test_o_nome_da_porta_e_o_do_motor(self) -> None:
        self.assertEqual(montar()[1].nome, "espiao")


if __name__ == "__main__":
    unittest.main()
