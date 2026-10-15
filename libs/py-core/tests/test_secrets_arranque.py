"""Comportamento de arranque e janela de tolerancia, lado Python (KAM-010).

Cobre, caso a caso, o criterio de aceitacao: «um servico sem segredo obrigatorio
falha ao arrancar com mensagem que nomeia o segredo (nunca o valor); em `prod`,
se o cofre estiver inacessivel no arranque, o servico nao arranca; depois do
arranque mantem o ultimo valor conhecido durante 15 min».

O ultimo caso desta modulo e o que impede as duas implementacoes de divergirem:
le a fonte TypeScript e exige o mesmo numero.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from kamba_core.secrets import (
    TTL_ULTIMO_VALOR_S,
    ArranqueAbortadoError,
    CofreInacessivelError,
    EnvSecretProvider,
    OpenBaoFakeProvider,
    SecretAusenteError,
    Secrets,
    nome_da_variavel,
)

ROOT = Path(__file__).resolve().parents[3]
OBRIGATORIOS = ("meta_app_secret", "meta_verify_token")


class Relogio:
    """Relogio de mentira, em segundos, que so avanca quando se manda."""

    def __init__(self, inicio: float = 1000.0) -> None:
        self.t = inicio

    def agora(self) -> float:
        return self.t

    def avancar(self, segundos: float) -> None:
        self.t += segundos


def env_com(valores: dict[str, str]) -> dict[str, str]:
    return {nome_da_variavel(ref): valor for ref, valor in valores.items()}


class TestArranque(unittest.TestCase):
    def test_arranca_com_todos_os_obrigatorios(self) -> None:
        secrets = Secrets.arrancar(
            servico="agr",
            provider=EnvSecretProvider(
                ambiente="dev",
                env=env_com(
                    {
                        "meta_app_secret": "valor-actual-de-teste",
                        "meta_verify_token": "valor-unico-de-teste",
                    }
                ),
            ),
            obrigatorios=OBRIGATORIOS,
        )
        self.assertEqual(secrets.provedor, "env")
        self.assertEqual(secrets.ambiente, "dev")
        self.assertTrue(secrets.e_obrigatorio("meta_app_secret"))
        self.assertEqual(secrets.get("meta_app_secret"), "valor-actual-de-teste")

    def test_sem_obrigatorio_nao_arranca_e_nomeia_todos(self) -> None:
        with self.assertRaises(ArranqueAbortadoError) as capturado:
            Secrets.arrancar(
                servico="agr",
                provider=EnvSecretProvider(ambiente="dev", env={}),
                obrigatorios=OBRIGATORIOS,
            )
        erro = capturado.exception
        self.assertEqual(erro.servico, "agr")
        # Um reinicio por segredo em falta e a forma mais cara de descobrir uma
        # configuracao incompleta.
        self.assertEqual(erro.segredos, ("meta_app_secret", "meta_verify_token"))
        self.assertIn("meta_app_secret, meta_verify_token", str(erro))

    def test_a_mensagem_nomeia_o_segredo_e_nunca_o_valor(self) -> None:
        valor = "valor-que-nao-pode-aparecer-em-lado-nenhum"
        with self.assertRaises(ArranqueAbortadoError) as capturado:
            Secrets.arrancar(
                servico="agr",
                # O primeiro existe, o segundo nao.
                provider=EnvSecretProvider(
                    ambiente="dev", env=env_com({"meta_app_secret": valor})
                ),
                obrigatorios=OBRIGATORIOS,
            )
        mensagem = str(capturado.exception)
        self.assertIn("meta_verify_token", mensagem)
        self.assertNotIn(valor, mensagem)

    def test_variavel_vazia_conta_como_ausente(self) -> None:
        env = env_com({"meta_verify_token": "valor-unico-de-teste"})
        env[nome_da_variavel("meta_app_secret")] = "   "
        with self.assertRaises(ArranqueAbortadoError) as capturado:
            Secrets.arrancar(
                servico="agr",
                provider=EnvSecretProvider(ambiente="dev", env=env),
                obrigatorios=OBRIGATORIOS,
            )
        self.assertEqual(capturado.exception.segredos, ("meta_app_secret",))

    def test_em_prod_cofre_inacessivel_no_arranque_nao_arranca(self) -> None:
        selado = OpenBaoFakeProvider(
            ambiente="prod",
            dados={"meta_app_secret": ("valor-actual-de-teste",)},
            selado=True,
        )
        with self.assertRaises(ArranqueAbortadoError) as capturado:
            Secrets.arrancar(
                servico="agr", provider=selado, obrigatorios=["meta_app_secret"]
            )
        self.assertIn("cofre inacessivel", str(capturado.exception))
        # Nada de segredos nomeados: nem se chegou a pedir.
        self.assertEqual(capturado.exception.segredos, ())

    def test_fora_de_prod_avisa_e_aborta_ao_nao_conseguir_ler(self) -> None:
        avisos: list[str] = []
        selado = OpenBaoFakeProvider(
            ambiente="staging",
            dados={"meta_app_secret": ("valor-actual-de-teste",)},
            selado=True,
        )
        with self.assertRaises(ArranqueAbortadoError) as capturado:
            Secrets.arrancar(
                servico="agr",
                provider=selado,
                obrigatorios=["meta_app_secret"],
                aviso=avisos.append,
            )
        # Aborta igualmente, mas por uma razao melhor: nomeia o segredo.
        self.assertIn("cofre inacessivel ao carregar", str(capturado.exception))
        self.assertEqual(capturado.exception.segredos, ("meta_app_secret",))
        self.assertEqual(len(avisos), 1)
        self.assertIn("a continuar em staging", avisos[0])


class TestJanela(unittest.TestCase):
    def test_a_janela_sao_quinze_minutos(self) -> None:
        self.assertEqual(TTL_ULTIMO_VALOR_S, 900)

    def test_a_janela_e_a_mesma_do_lado_typescript(self) -> None:
        """Se as duas implementacoes divergirem, o mesmo cofre passa a ter duas
        politicas de tolerancia — e o KAM-072 tem de rodar as duas.
        """
        fonte = (
            ROOT / "packages" / "core-ts" / "src" / "secrets" / "arranque.ts"
        ).read_text(encoding="utf-8")
        achado = re.search(
            r"TTL_ULTIMO_VALOR_MS\s*=\s*(\d+)\s*\*\s*(\d+)\s*\*\s*(\d+)", fonte
        )
        self.assertIsNotNone(achado, "nao encontrei TTL_ULTIMO_VALOR_MS na fonte TS")
        assert achado is not None
        ms = int(achado.group(1)) * int(achado.group(2)) * int(achado.group(3))
        self.assertEqual(ms, TTL_ULTIMO_VALOR_S * 1000)

    def test_serve_o_ultimo_valor_conhecido_dentro_da_janela(self) -> None:
        relogio = Relogio()
        avisos: list[str] = []
        cofre = OpenBaoFakeProvider(
            ambiente="prod",
            dados={
                "meta_app_secret": ("valor-anterior-de-teste", "valor-actual-de-teste")
            },
        )
        secrets = Secrets.arrancar(
            servico="agr",
            provider=cofre,
            obrigatorios=["meta_app_secret"],
            agora=relogio.agora,
            aviso=avisos.append,
        )

        cofre.selar()

        relogio.avancar(1)
        self.assertEqual(
            secrets.get_ring("meta_app_secret"),
            ("valor-actual-de-teste", "valor-anterior-de-teste"),
        )

        relogio.avancar(TTL_ULTIMO_VALOR_S - 2)
        self.assertEqual(secrets.get("meta_app_secret"), "valor-actual-de-teste")

        # No limite exacto deixa de servir: o limite e `>=` e nao `>` de
        # proposito — uma janela de 15 minutos que serve ao minuto 15 tem 15
        # minutos e um tique.
        relogio.avancar(1)
        with self.assertRaises(CofreInacessivelError):
            secrets.get("meta_app_secret")

        self.assertEqual(len(avisos), 2)
        for aviso in avisos:
            self.assertIn("ultimo valor conhecido de meta_app_secret", aviso)
            self.assertNotIn("valor-actual-de-teste", aviso)

        cofre.destrancar()
        self.assertEqual(secrets.get("meta_app_secret"), "valor-actual-de-teste")

    def test_a_janela_cobre_indisponibilidade_nao_revogacao(self) -> None:
        # Se a cache tapasse tambem o segredo apagado, revogar um token
        # comprometido deixaria de o desactivar durante quinze minutos — e
        # revogar e a accao que tem de ser imediata (`docs/tecnica/08` §10).
        relogio = Relogio()
        env = env_com({"meta_app_secret": "valor-actual-de-teste"})
        secrets = Secrets.arrancar(
            servico="agr",
            provider=EnvSecretProvider(ambiente="prod", env=env),
            obrigatorios=["meta_app_secret"],
            agora=relogio.agora,
        )
        del env[nome_da_variavel("meta_app_secret")]
        relogio.avancar(1)
        with self.assertRaises(SecretAusenteError):
            secrets.get("meta_app_secret")

    def test_um_segredo_nunca_lido_nao_tem_ultimo_valor(self) -> None:
        # A janela nao e um cofre alternativo: so cobre o que ja se leu uma vez.
        cofre = OpenBaoFakeProvider(
            ambiente="prod",
            dados={
                "meta_app_secret": ("valor-actual-de-teste",),
                "pepper_contact_hmac": ("pepper-de-teste",),
            },
        )
        secrets = Secrets.arrancar(
            servico="agr", provider=cofre, obrigatorios=["meta_app_secret"]
        )
        cofre.selar()
        with self.assertRaises(CofreInacessivelError):
            secrets.get("pepper_contact_hmac")


if __name__ == "__main__":
    unittest.main()
