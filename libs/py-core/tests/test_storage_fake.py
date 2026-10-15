"""O que e so do *fake* (KAM-011): as URLs que assina, e o que guarda.

O comportamento visto pela porta esta na bateria de contrato; aqui ficam as
arestas de `buscar`, que e a unica coisa que o *fake* tem e um servidor nao.
Espelho de `packages/core-ts/tests/storage.fake.test.ts`.
"""

from __future__ import annotations

import re
import unittest
from datetime import UTC, datetime

from storage_apoio import Relogio

from kamba_core.storage import Ctx, ObjectMeta, RespostaFake, criar_storage_fake, nova_chave
from kamba_core.storage.fake import ESQUEMA_FAKE

CTX = Ctx("aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa")
META = ObjectMeta("audio/ogg", "audio", datetime(2026, 10, 13, 8, 30, tzinfo=UTC))
RECUSADO = RespostaFake(403, b"")


class Fake(unittest.TestCase):
    def test_a_url_do_fake_tem_esquema_proprio(self) -> None:
        fake = criar_storage_fake()
        self.assertEqual(fake.storage.nome, "fake")
        ref = fake.storage.put(CTX, nova_chave(CTX, "audio"), b"abc", META)
        url = fake.storage.sign_url(CTX, ref, ttl_seconds=60)
        self.assertTrue(url.startswith(f"{ESQUEMA_FAKE}://objectos/{ref.key}?"))
        self.assertEqual(fake.total(), 1)
        self.assertEqual(fake.buscar(url), RespostaFake(200, b"abc"))

    def test_buscar_recusa_tudo_o_que_nao_e_uma_url_sua_intacta_e_no_prazo(self) -> None:
        relogio = Relogio()
        fake = criar_storage_fake(relogio.agora)
        ref = fake.storage.put(CTX, nova_chave(CTX, "audio"), b"abc", META)
        url = fake.storage.sign_url(CTX, ref, ttl_seconds=60)
        expira = re.search(r"expira=(\d+)", url).group(1)  # type: ignore[union-attr]

        outro = criar_storage_fake(relogio.agora)
        ref_outro = outro.storage.put(CTX, ref.key, b"abc", META)
        url_de_outro = outro.storage.sign_url(CTX, ref_outro, ttl_seconds=60)

        for adulterada in (
            "isto nao e uma URL",
            "",
            "http://[",
            None,
            7,
            url.replace(f"{ESQUEMA_FAKE}:", "https:"),
            url.replace("//objectos/", "//outro/"),
            url.replace(f"expira={expira}", f"expira={int(expira) + 3600}"),
            url.replace(f"expira={expira}", "expira=amanha"),
            url.replace(f"expira={expira}", "expira=-1"),
            url.replace(f"expira={expira}", "expira=١٠"),
            re.sub(r"assinatura=[0-9a-f]+", "assinatura=", url),
            re.sub(r"assinatura=[0-9a-f]+", "assinatura=" + "0" * 64, url),
            re.sub(r"assinatura=[0-9a-f]+", "assinatura=não-ascii", url),
            re.sub(r"assinatura=([0-9a-f]+)", r"assinatura=\1ff", url),
            re.sub(r"&assinatura=[0-9a-f]+", "", url),
            url_de_outro,
        ):
            with self.subTest(adulterada=str(adulterada)[:60]):
                self.assertEqual(fake.buscar(adulterada), RECUSADO)  # type: ignore[arg-type]

        # No limite: 59 s serve, 60 s ja nao.
        relogio.avancar(59)
        self.assertEqual(fake.buscar(url).estado, 200)
        relogio.avancar(1)
        self.assertEqual(fake.buscar(url).estado, 403)

    def test_url_valida_de_objecto_apagado_da_404_e_o_fake_copia_o_que_recebe(self) -> None:
        fake = criar_storage_fake()
        dados = bytearray(b"abc")
        ref = fake.storage.put(CTX, nova_chave(CTX, "audio"), dados, META)
        dados[0] = 0
        url = fake.storage.sign_url(CTX, ref, ttl_seconds=60)
        self.assertEqual(fake.buscar(url).corpo, b"abc", "o put copiou")

        fake.storage.delete(CTX, ref)
        self.assertEqual(fake.buscar(url), RespostaFake(404, b""))
        self.assertEqual(fake.total(), 0)


if __name__ == "__main__":
    unittest.main()
