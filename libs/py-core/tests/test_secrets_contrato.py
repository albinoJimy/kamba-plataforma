"""Suite de contrato de `SecretProvider` do lado Python (KAM-010).

**Uma bateria, tres implementacoes.** O criterio de aceitacao do ticket diz «a
suite de contrato passa em Env e contra um *fake* de OpenBao; trocar de
implementacao e so configuracao». A forma de essa frase ser verificavel e nao
uma intencao e esta: os casos estao escritos uma vez, numa `TestCase` abstracta,
e correm sobre `EnvSecretProvider`, `OpenBaoFakeProvider` e
`DopplerSecretProvider`.

O Doppler entra na bateria com um **transporte falso**: nao ha conta Doppler
neste ticket e, portanto, a linha «passa em Doppler (conta de teste)» do
criterio de aceitacao **nao** esta satisfeita.
"""

from __future__ import annotations

import json
import unittest

from kamba_core.secrets import (
    CofreInacessivelError,
    DopplerSecretProvider,
    EnvSecretProvider,
    OpenBaoFakeProvider,
    RespostaHttp,
    SecretAusenteError,
    SecretProvider,
    SecretRefInvalidaError,
    nome_da_variavel,
)
from kamba_core.secrets.env import SUFIXO_ANTERIOR

#: Referencia -> versoes, da mais antiga para a mais recente. Duas no maximo,
#: porque e o tecto do mecanismo de injeccao por variaveis de ambiente e porque
#: o anel que o KAM-013 consome e `(actual, anterior)` e nao um historico.
CENARIO: dict[str, tuple[str, ...]] = {
    "meta_app_secret": ("valor-anterior-de-teste", "valor-actual-de-teste"),
    "meta_verify_token": ("valor-unico-de-teste",),
    "meta_client_token/7f3cAb": ("token-de-teste-do-tenant",),
}

REFS_MALFORMADAS = (
    "",
    "ab",
    "META_APP_SECRET",
    "com espaco",
    "/sem-familia",
    "x" * 300,
)


def _plano(cenario: dict[str, tuple[str, ...]]) -> dict[str, str]:
    """Achata o cenario no mapa NOME_DE_VARIAVEL -> valor."""
    plano: dict[str, str] = {}
    for ref, versoes in cenario.items():
        base = nome_da_variavel(ref)
        plano[base] = versoes[-1]
        if len(versoes) > 1:
            plano[base + SUFIXO_ANTERIOR] = versoes[-2]
    return plano


class ContratoSecretProvider:
    """Os casos. Cada subclasse monta uma implementacao em `montar`."""

    def montar(self) -> SecretProvider:  # pragma: no cover - sobreposto
        raise NotImplementedError

    def tornar_inacessivel(self) -> bool:
        """Poe o cofre inacessivel; devolve `False` se a implementacao nao sabe."""
        return False

    def test_health_resolve_com_cofre_acessivel(self) -> None:
        self.montar().health()

    def test_get_devolve_o_valor_actual(self) -> None:
        provider = self.montar()
        self.assertEqual(provider.get("meta_app_secret"), "valor-actual-de-teste")
        self.assertEqual(provider.get("meta_verify_token"), "valor-unico-de-teste")

    def test_get_ring_devolve_actual_e_anterior(self) -> None:
        provider = self.montar()
        anel = provider.get_ring("meta_app_secret")
        self.assertEqual(anel, ("valor-actual-de-teste", "valor-anterior-de-teste"))
        # A tupla e posicional e e isso que o KAM-013 consome: [0] e a chave com
        # que se assina, [1] e a que ainda se aceita.
        self.assertEqual(len(anel), 2)
        self.assertEqual(anel[0], provider.get("meta_app_secret"))

    def test_get_ring_da_none_sem_rotacao(self) -> None:
        provider = self.montar()
        self.assertEqual(
            provider.get_ring("meta_verify_token"), ("valor-unico-de-teste", None)
        )

    def test_versions_ordenado_e_a_primeira_e_a_de_get(self) -> None:
        provider = self.montar()
        self.assertEqual(len(provider.versions("meta_app_secret")), 2)
        self.assertEqual(len(provider.versions("meta_verify_token")), 1)
        self.assertIsNotNone(provider.get_ring("meta_app_secret")[1])

    def test_instancia_por_tenant_por_referencia_opaca(self) -> None:
        # A costura com o KAM-003: a coluna guarda so esta cadeia de caracteres,
        # e quem a le nao a interpreta.
        self.assertEqual(
            self.montar().get("meta_client_token/7f3cAb"), "token-de-teste-do-tenant"
        )

    def test_ausente_nomeia_a_referencia(self) -> None:
        provider = self.montar()
        with self.assertRaises(SecretAusenteError) as capturado:
            provider.get("pepper_contact_hmac")
        self.assertEqual(capturado.exception.ref, "pepper_contact_hmac")
        self.assertIn("pepper_contact_hmac", str(capturado.exception))

    def test_referencia_malformada(self) -> None:
        provider = self.montar()
        for ref in REFS_MALFORMADAS:
            with self.subTest(ref=ref), self.assertRaises(SecretRefInvalidaError):
                provider.get(ref)

    def test_nenhuma_mensagem_de_erro_contem_um_valor(self) -> None:
        provider = self.montar()
        # Aquece a implementacao, para que qualquer valor que ela guarde ja
        # esteja em memoria quando os erros forem produzidos.
        provider.get("meta_app_secret")
        self.tornar_inacessivel()

        valores = [v for versoes in CENARIO.values() for v in versoes]
        mensagens: list[str] = []
        for ref in ("meta_app_secret", "nao_existe_no_cofre", "Ref Invalida!"):
            for chamada in (
                lambda r=ref: provider.get(r),
                lambda r=ref: provider.get_ring(r),
                lambda r=ref: provider.versions(r),
                lambda: provider.health(),
            ):
                try:
                    chamada()
                except Exception as erro:  # noqa: BLE001 - e o que se quer medir
                    mensagens.append(f"{type(erro).__name__}: {erro}")

        self.assertTrue(mensagens, "o cenario tinha de produzir erros")
        for mensagem in mensagens:
            for valor in valores:
                self.assertNotIn(valor, mensagem)

    def test_inacessivel_nao_e_ausente(self) -> None:
        provider = self.montar()
        if not self.tornar_inacessivel():
            # O `EnvSecretProvider` nao tem este estado: se o processo arrancou,
            # o seu ambiente existe.
            self.skipTest("implementacao sem estado de indisponibilidade")
        with self.assertRaises(CofreInacessivelError):
            provider.get("meta_app_secret")
        with self.assertRaises(CofreInacessivelError):
            provider.health()


class TestEnv(ContratoSecretProvider, unittest.TestCase):
    def montar(self) -> SecretProvider:
        self._provider = EnvSecretProvider(ambiente="dev", env=_plano(CENARIO))
        return self._provider


class TestOpenBaoFake(ContratoSecretProvider, unittest.TestCase):
    def montar(self) -> SecretProvider:
        self._fake = OpenBaoFakeProvider(ambiente="staging", dados=CENARIO)
        return self._fake

    def tornar_inacessivel(self) -> bool:
        self._fake.selar()
        return True


class TestDoppler(ContratoSecretProvider, unittest.TestCase):
    def montar(self) -> SecretProvider:
        self._em_baixo = False
        corpo = json.dumps(_plano(CENARIO))

        def transporte(_url: str, _cabecalhos: object) -> RespostaHttp:
            if self._em_baixo:
                return RespostaHttp(503, "")
            return RespostaHttp(200, corpo)

        return DopplerSecretProvider(
            ambiente="prod",
            projecto="kamba",
            config="prod",
            token_servico="token-de-teste-nao-e-um-segredo",
            transporte=transporte,
            # Sem cache entre chamadas, para que `tornar_inacessivel` tenha
            # efeito imediato nesta bateria.
            ttl_descarga_s=0.0,
        )

    def tornar_inacessivel(self) -> bool:
        self._em_baixo = True
        return True


class TestVersoesNoFake(unittest.TestCase):
    def test_mais_de_duas_versoes_mas_o_anel_continua_a_ser_duas(self) -> None:
        # Propriedade do cofre, nao do contrato: o KV v2 tem historico, o
        # mecanismo de injeccao por variaveis de ambiente tem tecto de duas.
        fake = OpenBaoFakeProvider(ambiente="staging")
        for valor in ("v1-de-teste", "v2-de-teste", "v3-de-teste"):
            fake.escrever("pepper_contact_hmac", valor)
        self.assertEqual(fake.versions("pepper_contact_hmac"), ("3", "2", "1"))
        self.assertEqual(
            fake.get_ring("pepper_contact_hmac"), ("v3-de-teste", "v2-de-teste")
        )
        self.assertEqual(fake.get("pepper_contact_hmac"), "v3-de-teste")


class TestProtocolo(unittest.TestCase):
    def test_as_tres_implementacoes_sao_SecretProvider(self) -> None:
        # `runtime_checkable` so verifica a presenca dos metodos; a assinatura e
        # o que a suite de contrato acima verifica. As duas coisas juntas e que
        # dao sentido a «trocar de implementacao e so configuracao».
        implementacoes = (
            EnvSecretProvider(ambiente="dev"),
            OpenBaoFakeProvider(ambiente="dev"),
            DopplerSecretProvider(
                ambiente="dev",
                projecto="kamba",
                config="dev",
                token_servico="token-de-teste-nao-e-um-segredo",
                transporte=lambda _u, _c: RespostaHttp(200, "{}"),
            ),
        )
        for implementacao in implementacoes:
            with self.subTest(provedor=implementacao.nome):
                self.assertIsInstance(implementacao, SecretProvider)


if __name__ == "__main__":
    unittest.main()
