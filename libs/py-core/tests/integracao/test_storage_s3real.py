"""A bateria de contrato contra um servidor S3 **real**, do lado Python (KAM-011).

Nao corre no *gate* 4: esta numa pasta sem `__init__.py`, que o `discover` de
`libs/py-core/tests` nao recolhe, de proposito, e quem a
corre e `infra/storage/contrato.py`, que levanta um SeaweedFS descartavel,
fixado por *digest*, e a aponta para la. Sem as variaveis de ambiente **falha**
— nao salta: uma suite de integracao que salta em silencio e uma suite que
ninguem corre.

O caminho ate ao servidor e o de producao, sem atalhos: `ler_config` le as
`KAMBA_STORAGE_*`, as credenciais vem de um `EnvSecretProvider` (as duas
variaveis de segredo do armazenamento, ADR-L002), e o transporte e o
`http.client`.

Alem da bateria comum, prova que **a assinatura e mesmo verificada** — uma chave
errada e um pedido anonimo sao recusados. Sem isto, a bateria passava contra um
servidor que aceitasse tudo, e nao provava nada sobre o SigV4 escrito a mao.

Os tres testes de capacidade (envio em partes, URL com expiracao, *object lock*)
estao do lado TypeScript (`packages/core-ts/tests/integracao/`): sao perguntas ao
servidor, e fazem-se uma vez.
"""

from __future__ import annotations

import hashlib
import os
import sys
import time
import unittest
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from storage_apoio import Alvo  # noqa: E402
from storage_contrato import BateriaDeContrato  # noqa: E402

from kamba_core.secrets import EnvSecretProvider  # noqa: E402
from kamba_core.storage import (  # noqa: E402
    ArmazenamentoIndisponivelError,
    Ctx,
    ObjectMeta,
    ObjectRef,
    criar_storage_s3,
    ler_config,
    nova_chave,
)
from kamba_core.storage.s3 import PedidoHttp, transporte_por_http  # noqa: E402
from kamba_core.storage.sigv4 import Credenciais, assinar_pedido  # noqa: E402

AMBIENTE = os.environ.get("KAMBA_ENV", "dev")

# Falha aqui, com os nomes das variaveis em falta, se o orquestrador nao as deu.
CONFIG = ler_config(ambiente=AMBIENTE)
COFRE = EnvSecretProvider(ambiente=AMBIENTE)

META = ObjectMeta("audio/ogg", "audio", datetime(2026, 10, 13, 8, 30, tzinfo=UTC))


def buscar(url: str) -> tuple[int, bytes]:
    """`GET` anonimo: o que faz quem recebe uma URL."""
    try:
        with urllib.request.urlopen(url, timeout=60) as resposta:  # noqa: S310
            return resposta.status, resposta.read()
    except urllib.error.HTTPError as erro:
        return erro.code, erro.read()


def garantir_bucket() -> None:
    url = f"{CONFIG.endpoint}/{CONFIG.bucket}"
    cabecalhos = assinar_pedido(
        metodo="PUT",
        url=url,
        credenciais=Credenciais(
            COFRE.get("storage_access_key_id"),
            COFRE.get("storage_secret_access_key"),
        ),
        regiao=CONFIG.regiao,
        agora=datetime.now(UTC),
    )
    del cabecalhos["host"]
    resposta = transporte_por_http(60)(PedidoHttp("PUT", url, cabecalhos, b""))
    b"".join(resposta.corpo)
    # 409: ja existe (corridas repetidas contra o mesmo servidor).
    if resposta.estado not in (200, 409):
        raise AssertionError(f"criar o bucket devolveu HTTP {resposta.estado}")


def setUpModule() -> None:  # noqa: N802 - nome do unittest
    garantir_bucket()


class ContratoNoServidorReal(BateriaDeContrato, unittest.TestCase):
    def criar_alvo(self) -> Alvo:
        return Alvo(
            storage=criar_storage_s3(config=CONFIG, secrets=COFRE),
            buscar=buscar,
            avancar=time.sleep,
        )


class _CofreComChaveErrada:
    def get(self, ref: str) -> str:
        if ref == "storage_secret_access_key":
            return "valor-errado-de-teste"
        return COFRE.get(ref)


class AAssinaturaEVerificada(unittest.TestCase):
    def test_chave_errada_e_pedido_anonimo_sao_recusados(self) -> None:
        ctx = Ctx(str(uuid.uuid4()))
        dados = os.urandom(1024)

        bom = criar_storage_s3(config=CONFIG, secrets=COFRE)
        ref = bom.put(ctx, nova_chave(ctx, "audio"), dados, META)

        cofre_errado = _CofreComChaveErrada()
        errado = criar_storage_s3(config=CONFIG, secrets=cofre_errado)
        with self.assertRaises(ArmazenamentoIndisponivelError) as escrita:
            errado.put(ctx, nova_chave(ctx, "audio"), dados, META)
        self.assertEqual(escrita.exception.estado, 403)
        with self.assertRaises(ArmazenamentoIndisponivelError) as leitura:
            errado.get(ctx, ref)
        self.assertEqual(leitura.exception.estado, 403)
        # Uma URL assinada com a chave errada tambem nao abre nada.
        self.assertEqual(buscar(errado.sign_url(ctx, ref, ttl_seconds=60))[0], 403)

        self.assertEqual(buscar(f"{CONFIG.endpoint}/{CONFIG.bucket}/{ref.key}")[0], 403)
        self.assertEqual(buscar(f"{CONFIG.endpoint}/{CONFIG.bucket}?list-type=2")[0], 403)


#: Objectos de interoperabilidade: tenant, chaves e conteudo fixos, iguais em
#: `packages/core-ts/tests/integracao/storage.s3real.test.ts`.
INTEROP_CTX = Ctx("00000000-0000-4000-8000-00000000c0de")
INTEROP_CHAVE_PY = f"t/{INTEROP_CTX.tenant_id}/audio/2026/10/00000000-0000-4000-8000-0000000000b1"
INTEROP_CHAVE_TS = f"t/{INTEROP_CTX.tenant_id}/audio/2026/10/00000000-0000-4000-8000-0000000000a1"
INTEROP_DADOS = bytes(range(256)) * 4


class InteropEscreve(unittest.TestCase):
    """O orquestrador corre esta classe **antes** da suite TypeScript."""

    def test_python_escreve_o_objecto_que_o_typescript_vai_ler(self) -> None:
        storage = criar_storage_s3(config=CONFIG, secrets=COFRE)
        ref = storage.put(INTEROP_CTX, INTEROP_CHAVE_PY, INTEROP_DADOS, META)
        self.assertEqual(ref.sha256, hashlib.sha256(INTEROP_DADOS).hexdigest())


class InteropLe(unittest.TestCase):
    """O orquestrador corre esta classe **depois** da suite TypeScript."""

    def test_python_le_o_objecto_e_os_metadados_que_o_typescript_escreveu(self) -> None:
        storage = criar_storage_s3(config=CONFIG, secrets=COFRE)
        ref = ObjectRef(INTEROP_CHAVE_TS, len(INTEROP_DADOS))
        self.assertEqual(b"".join(storage.get(INTEROP_CTX, ref)), INTEROP_DADOS)
        info = storage.head(INTEROP_CTX, ref)
        self.assertEqual(info.classe, "audio")
        self.assertEqual(info.retain_until, META.retain_until)
        self.assertEqual(info.tamanho, len(INTEROP_DADOS))
        self.assertIn(INTEROP_CHAVE_TS, [r.key for r in storage.list(INTEROP_CTX, f"t/{INTEROP_CTX.tenant_id}/")])


if __name__ == "__main__":
    unittest.main()
