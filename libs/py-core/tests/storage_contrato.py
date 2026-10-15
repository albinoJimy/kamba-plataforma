"""A bateria de contrato de `StorageProvider`, do lado Python (KAM-011).

**Uma bateria, escrita uma vez.** O criterio de aceitacao 5 diz "a mesma suite
de contrato passa na implementacao *fake* e contra SeaweedFS". A forma de essa
frase ser verificavel e esta classe: nao herda de `TestCase` (para o `unittest`
nao a recolher sozinha) e quem a usa so tem de dizer como se cria o alvo.

Quem a usa:

- `test_storage_contrato.py` — sobre o *fake* e sobre o motor S3 ligado a um
  servidor S3 em memoria. Corre no *gate* 4.
- `tests/integracao/test_storage_s3real.py` — sobre o motor S3 ligado a um
  servidor real (SeaweedFS). **Nao** corre no *gate* 4.

Espelho de `packages/core-ts/tests/apoio/contrato-storage.ts`, caso a caso. Cada
caso usa tenants novos, com UUID aleatorio: os alvos reais nao se limpam entre
casos, e um caso nao pode depender do que outro deixou.
"""

from __future__ import annotations

import hashlib
import os
import uuid
from datetime import UTC, datetime

from storage_apoio import Alvo

from kamba_core.storage import (
    ChaveForaDoTenantError,
    Ctx,
    CtxEmFaltaError,
    ListagemTruncadaError,
    ObjectMeta,
    ObjectoInexistenteError,
    ObjectRef,
    StorageProvider,
    TtlInvalidoError,
    nova_chave,
    prefixo_do_tenant,
)

KB = 1024
MB = 1024 * 1024

PRAZO = datetime(2026, 10, 13, 8, 30, tzinfo=UTC)


def sha256(dados: bytes) -> str:
    return hashlib.sha256(dados).hexdigest()


def tenant() -> Ctx:
    return Ctx(str(uuid.uuid4()))


def guardar(
    storage: StorageProvider, ctx: Ctx, dados: bytes, classe: str = "audio"
) -> ObjectRef:
    return storage.put(
        ctx, nova_chave(ctx, classe), dados, ObjectMeta("audio/ogg", classe, PRAZO)
    )


class BateriaDeContrato:
    """Os casos. A subclasse define `criar_alvo` e herda tambem de `TestCase`."""

    def criar_alvo(self) -> Alvo:  # pragma: no cover - definido pela subclasse
        raise NotImplementedError

    def setUp(self) -> None:
        self.alvo = self.criar_alvo()
        self.storage = self.alvo.storage

    # --- CA2: ida e volta com checksum identico ------------------------------

    def _ida_e_volta(self, tamanho: int) -> None:
        ctx = tenant()
        original = os.urandom(tamanho)
        soma = sha256(original)

        ref = guardar(self.storage, ctx, original)
        self.assertEqual(ref.tamanho, tamanho)
        self.assertEqual(ref.sha256, soma, "a soma que `put` devolve e a do que foi enviado")

        devolvido = hashlib.sha256()
        lidos = 0
        for bloco in self.storage.get(ctx, ref):
            devolvido.update(bloco)
            lidos += len(bloco)
        self.assertEqual(lidos, tamanho)
        self.assertEqual(devolvido.hexdigest(), soma, "o que volta e o que foi")

    def test_ida_e_volta_de_1_kb_com_checksum_identico(self) -> None:
        self._ida_e_volta(1 * KB)

    def test_ida_e_volta_de_10_mb_com_checksum_identico(self) -> None:
        self._ida_e_volta(10 * MB)

    def test_ida_e_volta_de_25_mb_com_checksum_identico(self) -> None:
        self._ida_e_volta(25 * MB)

    def test_o_corpo_pode_ser_um_fluxo_em_blocos_de_tamanho_irregular(self) -> None:
        ctx = tenant()
        original = os.urandom(300 * KB + 17)
        passo = 7 * KB + 3
        blocos = (original[i : i + passo] for i in range(0, len(original), passo))
        ref = self.storage.put(
            ctx, nova_chave(ctx, "imagem"), blocos, ObjectMeta("image/jpeg", "imagem", PRAZO)
        )
        self.assertEqual(ref.sha256, sha256(original))
        self.assertEqual(sha256(b"".join(self.storage.get(ctx, ref))), sha256(original))

    def test_um_objecto_vazio_e_um_objecto(self) -> None:
        ctx = tenant()
        ref = guardar(self.storage, ctx, b"")
        self.assertEqual(ref.tamanho, 0)
        self.assertEqual(b"".join(self.storage.get(ctx, ref)), b"")

    # --- CA8: metadados --------------------------------------------------------

    def test_cada_objecto_leva_classe_e_retain_until_lidos_do_servidor(self) -> None:
        ctx = tenant()
        key = nova_chave(ctx, "audio")
        ref = self.storage.put(
            ctx, key, os.urandom(2 * KB), ObjectMeta("audio/ogg; codecs=opus", "audio", PRAZO)
        )
        info = self.storage.head(ctx, ref)
        self.assertEqual(info.key, key)
        self.assertEqual(info.classe, "audio")
        self.assertEqual(info.retain_until, PRAZO)
        self.assertEqual(info.tamanho, 2 * KB)
        self.assertRegex(info.content_type, r"^audio/ogg")

    # --- CA3: URL assinada -----------------------------------------------------

    def test_sign_url_recusa_ttl_acima_de_300_e_tudo_o_que_nao_e_inteiro_positivo(self) -> None:
        ctx = tenant()
        ref = guardar(self.storage, ctx, os.urandom(KB))
        for ttl in (301, 3600, 0, -1, 1.5, float("nan"), float("inf"), "60", None, True):
            with self.subTest(ttl=ttl), self.assertRaises(TtlInvalidoError):
                self.storage.sign_url(ctx, ref, ttl_seconds=ttl)  # type: ignore[arg-type]
        # O limite e inclusivo: 300 serve.
        self.assertIsInstance(self.storage.sign_url(ctx, ref, ttl_seconds=300), str)

    def test_uma_url_com_ttl_de_60_s_devolve_200_antes_e_403_depois_de_65_s(self) -> None:
        ctx = tenant()
        original = os.urandom(4 * KB)
        ref = guardar(self.storage, ctx, original)

        url = self.storage.sign_url(ctx, ref, ttl_seconds=60)
        estado, corpo = self.alvo.buscar(url)
        self.assertEqual(estado, 200)
        self.assertEqual(sha256(corpo), sha256(original))

        self.alvo.avancar(65)
        estado, corpo = self.alvo.buscar(url)
        self.assertEqual(estado, 403, "a URL expirou")
        self.assertNotIn(original[:64], corpo)

    def test_uma_url_assinada_para_um_objecto_nao_abre_outro(self) -> None:
        a, b = tenant(), tenant()
        ref_a = guardar(self.storage, a, os.urandom(KB))
        conteudo_de_b = os.urandom(KB)
        ref_b = guardar(self.storage, b, conteudo_de_b)

        url = self.storage.sign_url(a, ref_a, ttl_seconds=60)
        self.assertIn(ref_a.key, url, "pre-condicao: a chave vai em claro na URL")
        estado, corpo = self.alvo.buscar(url.replace(ref_a.key, ref_b.key))
        self.assertEqual(estado, 403)
        self.assertNotIn(conteudo_de_b[:64], corpo)

    # --- delete e list ---------------------------------------------------------

    def test_delete_apaga_e_apagar_outra_vez_nao_e_erro(self) -> None:
        ctx = tenant()
        ref = guardar(self.storage, ctx, os.urandom(KB))
        self.storage.delete(ctx, ref)
        with self.assertRaises(ObjectoInexistenteError):
            b"".join(self.storage.get(ctx, ref))
        with self.assertRaises(ObjectoInexistenteError):
            self.storage.head(ctx, ref)
        self.storage.delete(ctx, ref)

    def test_list_devolve_o_que_esta_sob_o_prefixo_com_tamanhos_por_ordem(self) -> None:
        ctx = tenant()
        audios = [
            guardar(self.storage, ctx, os.urandom(10), "audio"),
            guardar(self.storage, ctx, os.urandom(20), "audio"),
        ]
        imagem = guardar(self.storage, ctx, os.urandom(30), "imagem")
        base = prefixo_do_tenant(ctx)

        tudo = self.storage.list(ctx, base)
        self.assertEqual([r.key for r in tudo], sorted(r.key for r in [*audios, imagem]))
        self.assertEqual(
            {r.key: r.tamanho for r in tudo},
            {r.key: r.tamanho for r in [*audios, imagem]},
        )
        self.assertEqual(
            [r.key for r in self.storage.list(ctx, f"{base}audio/")],
            sorted(r.key for r in audios),
        )
        self.assertEqual(self.storage.list(ctx, f"{base}video/"), [])

    def test_list_nao_corta_em_silencio_acima_do_limite_lanca(self) -> None:
        ctx = tenant()
        for _ in range(3):
            guardar(self.storage, ctx, os.urandom(8))
        with self.assertRaises(ListagemTruncadaError):
            self.storage.list(ctx, prefixo_do_tenant(ctx), limite=2)
        self.assertEqual(len(self.storage.list(ctx, prefixo_do_tenant(ctx), limite=3)), 3)

    # --- CA1 e CA4 (X-08): isolamento ------------------------------------------

    def test_x08_com_o_contexto_de_a_nada_de_b_se_le_assina_apaga_ou_lista(self) -> None:
        storage = self.storage
        a, b = tenant(), tenant()
        canario_de_b = os.urandom(2 * KB)
        ref_b = guardar(storage, b, canario_de_b)
        ref_a = guardar(storage, a, os.urandom(KB))

        # Metade positiva primeiro: B ve o seu, A ve o seu. "A nao ve B"
        # prova-se trivialmente com um armazenamento vazio.
        self.assertEqual(sha256(b"".join(storage.get(b, ref_b))), sha256(canario_de_b))
        self.assertEqual([r.key for r in storage.list(a, prefixo_do_tenant(a))], [ref_a.key])

        with self.assertRaises(ChaveForaDoTenantError):
            storage.get(a, ref_b)
        with self.assertRaises(ChaveForaDoTenantError):
            storage.head(a, ref_b)
        with self.assertRaises(ChaveForaDoTenantError):
            storage.sign_url(a, ref_b, ttl_seconds=60)
        with self.assertRaises(ChaveForaDoTenantError):
            storage.delete(a, ref_b)
        with self.assertRaises(ChaveForaDoTenantError):
            storage.list(a, prefixo_do_tenant(b))
        with self.assertRaises(ChaveForaDoTenantError):
            storage.list(a, f"{prefixo_do_tenant(b)}audio/")

        # Nenhuma listagem de A traz chaves de B, por nenhum prefixo que A possa pedir.
        for prefixo in (prefixo_do_tenant(a), f"{prefixo_do_tenant(a)}audio/"):
            for ref in storage.list(a, prefixo):
                self.assertTrue(ref.key.startswith(prefixo_do_tenant(a)))
                self.assertNotEqual(ref.key, ref_b.key)

        # E o que A tentou nao teve efeito: o objecto de B esta intacto.
        self.assertEqual(sha256(b"".join(storage.get(b, ref_b))), sha256(canario_de_b))

    def test_x08_a_nao_escreve_no_prefixo_de_b(self) -> None:
        a, b = tenant(), tenant()
        with self.assertRaises(ChaveForaDoTenantError):
            self.storage.put(
                a, nova_chave(b, "audio"), os.urandom(KB), ObjectMeta("audio/ogg", "audio", PRAZO)
            )
        self.assertEqual(self.storage.list(b, prefixo_do_tenant(b)), [], "nada foi escrito em B")

    def test_sem_ctx_tenant_id_nao_ha_operacao_nenhuma(self) -> None:
        ctx = tenant()
        ref = guardar(self.storage, ctx, os.urandom(KB))
        for sem_ctx in (Ctx(""), Ctx(None), None, object(), {}):  # type: ignore[arg-type]
            with self.subTest(ctx=sem_ctx):
                with self.assertRaises(CtxEmFaltaError):
                    self.storage.get(sem_ctx, ref)  # type: ignore[arg-type]
                with self.assertRaises(CtxEmFaltaError):
                    self.storage.head(sem_ctx, ref)  # type: ignore[arg-type]
                with self.assertRaises(CtxEmFaltaError):
                    self.storage.sign_url(sem_ctx, ref, ttl_seconds=60)  # type: ignore[arg-type]
                with self.assertRaises(CtxEmFaltaError):
                    self.storage.delete(sem_ctx, ref)  # type: ignore[arg-type]
                with self.assertRaises(CtxEmFaltaError):
                    self.storage.list(sem_ctx, prefixo_do_tenant(ctx))  # type: ignore[arg-type]
                with self.assertRaises(CtxEmFaltaError):
                    self.storage.put(
                        sem_ctx,  # type: ignore[arg-type]
                        ref.key,
                        os.urandom(8),
                        ObjectMeta("audio/ogg", "audio", PRAZO),
                    )
        # O objecto continua la: nenhuma das recusas apagou nada.
        self.assertEqual(self.storage.head(ctx, ref).tamanho, KB)
