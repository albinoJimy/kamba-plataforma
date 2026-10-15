"""Um caso negativo por regra, lado Python (KAM-010).

A suite de contrato prova que as tres implementacoes concordam. Esta prova que
cada **regra** recusa o que tem de recusar — a parte que costuma ficar sem
teste, porque ninguem escreve por acidente um teste de uma coisa que nao deve
acontecer.
"""

from __future__ import annotations

import json
import unittest

from kamba_core.secrets import (
    A_CONFIRMAR,
    PREFIXO,
    AmbienteErradoError,
    CofreInacessivelError,
    DopplerSecretProvider,
    EnvSecretProvider,
    OpenBaoFakeProvider,
    RespostaHttp,
    SecretAusenteError,
    SecretProvider,
    SecretRefInvalidaError,
    e_ambiente,
    familia_da_ref,
    interpretar_descarga_plana,
    nome_da_variavel,
    validar_ref,
)


def doppler(
    *,
    ambiente: str = "prod",
    config: str | None = None,
    token: str = "token-de-teste-nao-e-um-segredo",
    transporte=None,
    config_da_resposta=None,
) -> DopplerSecretProvider:
    return DopplerSecretProvider(
        ambiente=ambiente,
        projecto="kamba",
        config=ambiente if config is None else config,
        token_servico=token,
        transporte=transporte or (lambda _u, _c: RespostaHttp(200, "{}")),
        config_da_resposta=config_da_resposta,
        ttl_descarga_s=0.0,
    )


class TestFormaDaReferencia(unittest.TestCase):
    def test_recusa_maiusculas_espacos_e_familia_vazia(self) -> None:
        for ref in (
            "",
            "ab",
            "META_APP_SECRET",
            "meta app secret",
            "/so-instancia",
            "meta_app_secret/",
            "meta_app_secret/com espaco",
            "9comeca_por_digito",
            "x" * 300,
            None,
            7,
        ):
            with self.subTest(ref=ref), self.assertRaises(SecretRefInvalidaError):
                validar_ref(ref)

    def test_aceita_o_que_tem_de_aceitar(self) -> None:
        self.assertEqual(validar_ref("meta_app_secret"), "meta_app_secret")
        self.assertEqual(
            validar_ref("meta_client_token/7f3cAb-9.x:1"),
            "meta_client_token/7f3cAb-9.x:1",
        )

    def test_a_mensagem_diz_o_comprimento_nao_o_conteudo(self) -> None:
        # Se alguem passar um **valor** onde devia passar uma referencia, o valor
        # nao pode sair pela mensagem de erro.
        valor_por_engano = "um-valor-que-alguem-passou-por-engano-em-vez-da-referencia"
        with self.assertRaises(SecretRefInvalidaError) as capturado:
            validar_ref(valor_por_engano)
        mensagem = str(capturado.exception)
        self.assertNotIn(valor_por_engano, mensagem)
        self.assertIn(f"{len(valor_por_engano)} caracteres", mensagem)

    def test_familia_e_ambiente(self) -> None:
        self.assertEqual(familia_da_ref("meta_app_secret"), "meta_app_secret")
        self.assertEqual(familia_da_ref("meta_client_token/7f3cAb"), "meta_client_token")
        self.assertTrue(e_ambiente("prod"))
        self.assertFalse(e_ambiente("producao"))
        self.assertFalse(e_ambiente(3))


class TestNomeDaVariavel(unittest.TestCase):
    def test_a_instancia_mantem_a_caixa(self) -> None:
        # Se a instancia subisse a maiusculas, `.../7f3cab` e `.../7F3CAB`
        # designariam a mesma variavel — e um tenant leria o token de outro.
        self.assertNotEqual(
            nome_da_variavel("meta_client_token/7f3cab"),
            nome_da_variavel("meta_client_token/7F3CAB"),
        )
        self.assertEqual(
            nome_da_variavel("meta_app_secret"), f"{PREFIXO}META_APP_SECRET"
        )
        self.assertEqual(
            nome_da_variavel("meta_client_token/7f3cAb-9.x"),
            f"{PREFIXO}META_CLIENT_TOKEN__7f3cAb_9_x",
        )

    def test_a_regra_e_a_mesma_do_lado_typescript(self) -> None:
        """Se as duas implementacoes divergirem, o mesmo cofre passa a ter dois
        esquemas de nomes e `doppler run -- ...` serve um servico e nao o outro.
        """
        from pathlib import Path

        fonte = (
            Path(__file__).resolve().parents[3]
            / "packages"
            / "core-ts"
            / "src"
            / "secrets"
            / "env.ts"
        ).read_text(encoding="utf-8")
        self.assertIn('PREFIXO = "KAMBA_SECRET_"', fonte)
        self.assertIn('SUFIXO_ANTERIOR = "_ANTERIOR"', fonte)
        # A instancia nao sobe a maiusculas do lado TS tambem: so a familia.
        self.assertIn("familia = limpo.slice(0, corte).toUpperCase()", fonte)


class TestEnvNegativos(unittest.TestCase):
    def test_vazio_e_so_espacos_contam_como_ausencia(self) -> None:
        provider = EnvSecretProvider(
            ambiente="dev",
            env={
                f"{PREFIXO}META_APP_SECRET": "",
                f"{PREFIXO}META_VERIFY_TOKEN": "   ",
            },
        )
        with self.assertRaises(SecretAusenteError):
            provider.get("meta_app_secret")
        with self.assertRaises(SecretAusenteError):
            provider.get_ring("meta_verify_token")
        with self.assertRaises(SecretAusenteError):
            provider.versions("meta_app_secret")

    def test_anterior_vazio_nao_e_uma_versao(self) -> None:
        provider = EnvSecretProvider(
            ambiente="dev",
            env={
                f"{PREFIXO}META_APP_SECRET": "valor-actual-de-teste",
                f"{PREFIXO}META_APP_SECRET_ANTERIOR": "",
            },
        )
        self.assertEqual(
            provider.get_ring("meta_app_secret"), ("valor-actual-de-teste", None)
        )
        self.assertEqual(provider.versions("meta_app_secret"), ("actual",))


class TestCofreSelado(unittest.TestCase):
    def test_selado_nao_e_ausente(self) -> None:
        cofre = OpenBaoFakeProvider(
            ambiente="staging",
            dados={"meta_app_secret": ("valor-actual-de-teste",)},
            selado=True,
        )
        with self.assertRaises(CofreInacessivelError):
            cofre.get("meta_app_secret")
        cofre.destrancar()
        self.assertEqual(cofre.get("meta_app_secret"), "valor-actual-de-teste")

    def test_escrever_nao_pertence_a_porta(self) -> None:
        # `escrever` existe para montar cenarios. Nao esta em `SecretProvider`,
        # e o `Protocol` nao o exige: se um dia entrar, este teste tem de ser
        # reescrito de proposito e nao por distraccao.
        cofre = OpenBaoFakeProvider(ambiente="dev")
        self.assertIsInstance(cofre, SecretProvider)
        self.assertNotIn("escrever", SecretProvider.__protocol_attrs__)
        self.assertTrue(callable(cofre.escrever))


class TestAmbienteDoCofre(unittest.TestCase):
    def test_config_de_staging_contra_prod_e_recusada_na_construcao(self) -> None:
        # **Esta e a metade da regra que se consegue provar sem conta Doppler.**
        # A outra metade — o lado do servidor recusar um *service token* de
        # `staging` apresentado ao projecto `prod` — exige tres projectos reais e
        # fica por satisfazer neste ticket.
        with self.assertRaises(AmbienteErradoError) as capturado:
            doppler(ambiente="prod", config="staging")
        self.assertEqual(capturado.exception.esperado, "prod")
        self.assertEqual(capturado.exception.obtido, "staging")
        self.assertIn("recusado", str(capturado.exception))
        # E o caminho inverso tambem.
        with self.assertRaises(AmbienteErradoError):
            doppler(ambiente="staging", config="prod")

    def test_config_diferente_na_resposta_e_recusada(self) -> None:
        provider = doppler(
            ambiente="prod",
            transporte=lambda _u, _c: RespostaHttp(200, json.dumps({"config": "staging"})),
            config_da_resposta=lambda corpo: json.loads(corpo).get("config"),
        )
        with self.assertRaises(AmbienteErradoError):
            provider.get("meta_app_secret")
        # Esta guarda e condicional porque saber se a resposta real traz esta
        # informacao e NAO VERIFICADO.
        self.assertIn("se a resposta identifica", A_CONFIRMAR["identificacao_da_config"])


class TestCredenciaisETransporte(unittest.TestCase):
    def test_token_vazio_nao_constroi(self) -> None:
        with self.assertRaises(CofreInacessivelError):
            doppler(token="   ")

    def test_401_e_403_dizem_o_estado_e_o_projecto_nunca_o_corpo(self) -> None:
        corpo_sensivel = '{"messages":["token revogado"],"segredo":"nao-devia-sair"}'
        for status in (401, 403):
            with self.subTest(status=status):
                provider = doppler(
                    transporte=lambda _u, _c, s=status: RespostaHttp(s, corpo_sensivel)
                )
                with self.assertRaises(CofreInacessivelError) as capturado:
                    provider.get("meta_app_secret")
                mensagem = str(capturado.exception)
                self.assertIn(f"HTTP {status}", mensagem)
                self.assertIn("kamba/prod", mensagem)
                self.assertNotIn("nao-devia-sair", mensagem)

    def test_outro_estado_http_nao_leva_o_corpo(self) -> None:
        provider = doppler(
            transporte=lambda _u, _c: RespostaHttp(503, '{"valor":"nao-devia-sair"}')
        )
        with self.assertRaises(CofreInacessivelError) as capturado:
            provider.health()
        self.assertEqual(
            str(capturado.exception), "cofre inacessivel (provedor doppler): HTTP 503"
        )

    def test_corpo_que_nao_e_objecto_json(self) -> None:
        for corpo in ("isto-nao-e-json", "[]", '"texto"', "null"):
            with self.subTest(corpo=corpo):
                provider = doppler(transporte=lambda _u, _c, c=corpo: RespostaHttp(200, c))
                with self.assertRaises(CofreInacessivelError) as capturado:
                    provider.health()
                self.assertNotIn(corpo, str(capturado.exception))

    def test_transporte_que_explode_nao_deixa_escapar_a_mensagem(self) -> None:
        class ErroDeRede(OSError):
            pass

        def transporte(_url: str, _cabecalhos: object) -> RespostaHttp:
            raise ErroDeRede("connect ECONNREFUSED 10.0.0.1:443 token=nao-devia-sair")

        provider = doppler(transporte=transporte)
        with self.assertRaises(CofreInacessivelError) as capturado:
            provider.health()
        # So o **nome** da classe do erro atravessa.
        self.assertEqual(
            str(capturado.exception),
            "cofre inacessivel (provedor doppler): transporte falhou: ErroDeRede",
        )

    def test_a_interpretacao_por_omissao_ignora_valores_que_nao_sao_texto(self) -> None:
        # Fica documentado o que a suposicao NAO VERIFICADA faz com uma resposta
        # aninhada: ignora-a, em vez de inventar uma travessia.
        mapa = interpretar_descarga_plana(
            json.dumps({"A": "um", "B": 2, "C": None, "D": {"raw": "aninhado"}})
        )
        self.assertEqual(dict(mapa), {"A": "um"})
        self.assertIn("objecto plano", A_CONFIRMAR["resposta"])

    def test_reutiliza_a_descarga_dentro_do_ttl(self) -> None:
        chamadas = 0

        def transporte(_url: str, _cabecalhos: object) -> RespostaHttp:
            nonlocal chamadas
            chamadas += 1
            return RespostaHttp(200, json.dumps({f"{PREFIXO}META_APP_SECRET": "v"}))

        provider = DopplerSecretProvider(
            ambiente="dev",
            projecto="kamba",
            config="dev",
            token_servico="token-de-teste-nao-e-um-segredo",
            transporte=transporte,
            ttl_descarga_s=60.0,
            agora=lambda: 1.0,
        )
        provider.get("meta_app_secret")
        provider.get("meta_app_secret")
        provider.health()
        # Um pedido por segredo multiplicaria por vinte os acessos a um SaaS que
        # o `E4` §5 marca como risco de dependencia.
        self.assertEqual(chamadas, 1)


if __name__ == "__main__":
    unittest.main()
