"""Configuracao do armazenamento e destino dos dados (KAM-011, CA7).

O que se prova aqui e o arranque: sem `destino.country` ou `destino.provider`
nao ha configuracao; em `prod`, fora de Angola e sem `apd_ref`, nao ha servico;
e as credenciais vem do `SecretProvider`, nunca do ambiente `KAMBA_STORAGE_*`.

Espelho de `packages/core-ts/tests/storage.config.test.ts`.
"""

from __future__ import annotations

import os
import unittest
from datetime import UTC, datetime
from unittest import mock

from storage_apoio import CONFIG_DE_TESTE, CREDENCIAIS_DE_TESTE, Relogio, S3EmMemoria

from kamba_core.secrets import EnvSecretProvider, SecretAusenteError
from kamba_core.storage import (
    VARIAVEIS,
    ArmazenamentoIndisponivelError,
    ConfigDeArmazenamentoError,
    Ctx,
    DestinoDeArmazenamento,
    DestinoSemApdRefError,
    ObjectMeta,
    StorageConfig,
    criar_storage_s3,
    ler_config,
    nova_chave,
)
from kamba_core.storage.config import VAR_APD_REF, VAR_BUCKET, VAR_COUNTRY, VAR_ENDPOINT, VAR_PROVIDER, VAR_REGIAO

BOM = {
    "KAMBA_STORAGE_ENDPOINT": "http://seaweedfs:8333",
    "KAMBA_STORAGE_BUCKET": "kamba-dev",
    "KAMBA_STORAGE_REGION": "us-east-1",
    "KAMBA_STORAGE_DESTINO_COUNTRY": "AO",
    "KAMBA_STORAGE_DESTINO_PROVIDER": "seaweedfs_local",
}


def sem(*nomes: str) -> dict[str, str]:
    return {n: v for n, v in BOM.items() if n not in nomes}


class LerConfig(unittest.TestCase):
    def test_le_a_configuracao_completa_e_expoe_o_destino(self) -> None:
        self.assertEqual(
            ler_config(ambiente="prod", env=BOM),
            StorageConfig(
                endpoint="http://seaweedfs:8333",
                bucket="kamba-dev",
                regiao="us-east-1",
                destino=DestinoDeArmazenamento("AO", "seaweedfs_local", None),
                avisos=(),
            ),
        )
        # Espacos a volta nao mudam o valor; a barra final do endpoint tambem nao.
        com_espacos = ler_config(
            ambiente="dev",
            env={**BOM, VAR_ENDPOINT: " https://s3.exemplo.co.ao/ ", VAR_BUCKET: " kamba-dev "},
        )
        self.assertEqual(com_espacos.endpoint, "https://s3.exemplo.co.ao")
        self.assertEqual(com_espacos.bucket, "kamba-dev")
        # A porta por omissao do esquema nao fica no endpoint: e a forma que o
        # cabecalho `Host` leva, e a que foi assinada.
        self.assertEqual(
            ler_config(ambiente="dev", env={**BOM, VAR_ENDPOINT: "https://s3.exemplo.co.ao:443"}).endpoint,
            "https://s3.exemplo.co.ao",
        )

    def test_as_variaveis_sao_as_seis_do_lado_typescript(self) -> None:
        self.assertEqual(
            VARIAVEIS,
            (VAR_ENDPOINT, VAR_BUCKET, VAR_REGIAO, VAR_COUNTRY, VAR_PROVIDER, VAR_APD_REF),
        )
        self.assertEqual(VAR_COUNTRY, "KAMBA_STORAGE_DESTINO_COUNTRY")
        self.assertEqual(VAR_PROVIDER, "KAMBA_STORAGE_DESTINO_PROVIDER")
        self.assertEqual(VAR_APD_REF, "KAMBA_STORAGE_DESTINO_APD_REF")

    def test_o_arranque_falha_sem_destino_country_e_sem_destino_provider(self) -> None:
        for variavel in (VAR_COUNTRY, VAR_PROVIDER):
            for ambiente in ("dev", "staging", "prod"):
                for env in (sem(variavel), {**BOM, variavel: ""}, {**BOM, variavel: "   "}):
                    with self.subTest(variavel=variavel, ambiente=ambiente):
                        with self.assertRaises(ConfigDeArmazenamentoError) as apanhado:
                            ler_config(ambiente=ambiente, env=env)
                        self.assertEqual(apanhado.exception.problemas, (f"{variavel} em falta",))

    def test_todas_as_variaveis_em_falta_sao_nomeadas_de_uma_vez(self) -> None:
        with self.assertRaises(ConfigDeArmazenamentoError) as apanhado:
            ler_config(ambiente="dev", env={})
        self.assertEqual(
            apanhado.exception.problemas,
            (
                "KAMBA_STORAGE_ENDPOINT em falta",
                "KAMBA_STORAGE_BUCKET em falta",
                "KAMBA_STORAGE_REGION em falta",
                "KAMBA_STORAGE_DESTINO_COUNTRY em falta",
                "KAMBA_STORAGE_DESTINO_PROVIDER em falta",
            ),
        )
        for problema in apanhado.exception.problemas:
            self.assertIn(problema, str(apanhado.exception))

    def test_valores_mal_formados_sao_recusados_sem_serem_repetidos(self) -> None:
        casos = (
            (VAR_COUNTRY, "ao"),
            (VAR_COUNTRY, "AGO"),
            (VAR_COUNTRY, "Angola"),
            (VAR_COUNTRY, "A1"),
            (VAR_COUNTRY, "AO\nZA"),
            (VAR_PROVIDER, "SeaweedFS"),
            (VAR_PROVIDER, "x"),
            (VAR_PROVIDER, "com espaco"),
            (VAR_BUCKET, "Kamba_Dev"),
            (VAR_BUCKET, "a/b"),
            (VAR_REGIAO, "US EAST"),
            (VAR_APD_REF, "com espaco"),
            (VAR_APD_REF, "x" * 129),
            (VAR_ENDPOINT, "seaweedfs:8333"),
            (VAR_ENDPOINT, "ftp://seaweedfs:8333"),
            (VAR_ENDPOINT, "http://seaweedfs:8333/caminho"),
            (VAR_ENDPOINT, "http://seaweedfs:8333/?x=1"),
            (VAR_ENDPOINT, "http://seaweedfs:8333#f"),
            (VAR_ENDPOINT, "http://nome:passe@seaweedfs:8333"),
            (VAR_ENDPOINT, "http://seaweedfs:porta"),
            (VAR_ENDPOINT, "http://seaweedfs:99999"),
            (VAR_ENDPOINT, "http://com espaco:8333"),
            (VAR_ENDPOINT, "http://"),
            (VAR_ENDPOINT, "isto nao e uma URL"),
        )
        for variavel, valor in casos:
            with self.subTest(variavel=variavel, valor=valor):
                with self.assertRaises(ConfigDeArmazenamentoError) as apanhado:
                    ler_config(ambiente="dev", env={**BOM, variavel: valor})
                self.assertEqual(len(apanhado.exception.problemas), 1)
                self.assertTrue(
                    apanhado.exception.problemas[0].startswith(f"{variavel} mal formada")
                )
                # (`ao` e `x` aparecem em qualquer frase; os outros nao.)
                if len(valor) > 3:
                    self.assertNotIn(valor, str(apanhado.exception))

    def test_em_prod_um_destino_fora_de_angola_sem_apd_ref_impede_o_arranque(self) -> None:
        for country in ("ZA", "DE", "US", "PT", "NA"):
            with self.subTest(country=country):
                env = {**BOM, VAR_COUNTRY: country, VAR_PROVIDER: "s3_gerido"}
                with self.assertRaises(DestinoSemApdRefError) as apanhado:
                    ler_config(ambiente="prod", env=env)
                self.assertEqual(apanhado.exception.country, country)
                self.assertEqual(apanhado.exception.provider, "s3_gerido")
                self.assertIn("KAMBA_STORAGE_DESTINO_APD_REF", str(apanhado.exception))
                self.assertIn("nao arranca", str(apanhado.exception))
                # Uma variavel vazia e uma variavel ausente: nao serve de referencia.
                with self.assertRaises(DestinoSemApdRefError):
                    ler_config(ambiente="prod", env={**env, VAR_APD_REF: "  "})
                # Nenhum pais e tratado como "adequado": com a referencia,
                # arranca; sem ela, nao.
                com_ref = ler_config(ambiente="prod", env={**env, VAR_APD_REF: "APD/2026/0042"})
                self.assertEqual(
                    com_ref.destino, DestinoDeArmazenamento(country, "s3_gerido", "APD/2026/0042")
                )
                self.assertEqual(com_ref.avisos, ())

    def test_em_prod_angola_arranca_sem_apd_ref(self) -> None:
        config = ler_config(ambiente="prod", env=BOM)
        self.assertEqual(config.destino.country, "AO")
        self.assertIsNone(config.destino.apd_ref)
        self.assertEqual(config.avisos, ())

    def test_fora_de_prod_o_mesmo_destino_arranca_com_um_aviso(self) -> None:
        for ambiente in ("dev", "staging"):
            config = ler_config(ambiente=ambiente, env={**BOM, VAR_COUNTRY: "ZA"})
            self.assertEqual(config.destino.country, "ZA")
            self.assertEqual(len(config.avisos), 1)
            self.assertIn("ZA", config.avisos[0])
            self.assertIn("em prod isto impede o arranque", config.avisos[0])

    def test_a_configuracao_mal_formada_ganha_a_regra_do_destino(self) -> None:
        with self.assertRaises(ConfigDeArmazenamentoError):
            ler_config(ambiente="prod", env={**sem(VAR_BUCKET), VAR_COUNTRY: "ZA"})

    def test_le_o_ambiente_do_processo_quando_nao_lhe_dao_nenhum(self) -> None:
        limpo = {n: v for n, v in os.environ.items() if n not in VARIAVEIS}
        with mock.patch.dict(os.environ, limpo, clear=True):
            with self.assertRaises(ConfigDeArmazenamentoError):
                ler_config(ambiente="dev")
        with mock.patch.dict(os.environ, {**limpo, **BOM}, clear=True):
            self.assertEqual(ler_config(ambiente="dev").bucket, "kamba-dev")


class AsCredenciaisVemDoSecretProvider(unittest.TestCase):
    def test_pelas_referencias_do_inventario_e_em_cada_pedido(self) -> None:
        relogio = Relogio()
        servidor = S3EmMemoria(
            bucket=CONFIG_DE_TESTE.bucket,
            regiao=CONFIG_DE_TESTE.regiao,
            credenciais=CREDENCIAIS_DE_TESTE,
            agora=relogio.agora,
        )
        ctx = Ctx("aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa")
        meta = ObjectMeta("audio/ogg", "audio", datetime(2026, 10, 13, tzinfo=UTC))

        # O provedor real do KAM-010, a ler o ambiente que o ADR-L002 descreve.
        env = {
            "KAMBA_SECRET_STORAGE_ACCESS_KEY_ID": CREDENCIAIS_DE_TESTE.access_key_id,
            "KAMBA_SECRET_STORAGE_SECRET_ACCESS_KEY": CREDENCIAIS_DE_TESTE.secret_access_key,
        }
        cofre = EnvSecretProvider(ambiente="dev", env=env)
        storage = criar_storage_s3(
            config=CONFIG_DE_TESTE,
            secrets=cofre,
            transporte=servidor.transporte,
            agora=relogio.agora,
        )
        ref = storage.put(ctx, nova_chave(ctx, "audio"), b"12345678", meta)
        self.assertEqual(ref.tamanho, 8)

        # Rotacao: o valor muda no cofre e o pedido seguinte ja usa o novo — sem
        # reiniciar nada. O servidor ainda so conhece o antigo, pelo que recusa.
        env["KAMBA_SECRET_STORAGE_SECRET_ACCESS_KEY"] = "valor-rodado"
        with self.assertRaises(ArmazenamentoIndisponivelError) as recusado:
            storage.get(ctx, ref)
        self.assertEqual(recusado.exception.estado, 403)

        # Sem o segredo, a operacao falha com o nome dele — e nada chega a rede.
        del env["KAMBA_SECRET_STORAGE_SECRET_ACCESS_KEY"]
        antes = len(servidor.pedidos)
        with self.assertRaises(SecretAusenteError) as ausente:
            storage.get(ctx, ref)
        self.assertEqual(ausente.exception.ref, "storage_secret_access_key")
        self.assertEqual(len(servidor.pedidos), antes, "sem credenciais nao ha pedido")


if __name__ == "__main__":
    unittest.main()
