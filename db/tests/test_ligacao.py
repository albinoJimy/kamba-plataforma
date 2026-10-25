"""`ligacao`: configuracao lida do ambiente, sem tocar em base nenhuma.

Estes casos nao precisam de PostgreSQL e nao passam pelo trinco `*_gate8`:
verificam so o que acontece **antes** de haver ligacao — que e onde uma
configuracao errada tem de ser apanhada.
"""

from __future__ import annotations

import unittest

import ligacao

COMPLETO = {
    "KAMBA_DB_NAME": "kamba_gate8",
    "POSTGRES_USER": "kamba",
    "POSTGRES_PASSWORD": "valor-admin",
    "KAMBA_SECRET_DB_MIGRATOR_PASSWORD": "valor-migrator",
    "KAMBA_SECRET_DB_APP_PASSWORD": "valor-app",
    "KAMBA_SECRET_DB_BATCH_PASSWORD": "valor-batch",
}


class TestAlvo(unittest.TestCase):
    def test_omissoes_de_host_e_porta(self) -> None:
        self.assertEqual(
            ligacao.alvo({"KAMBA_DB_NAME": "kamba_gate8"}),
            ligacao.Alvo("127.0.0.1", 5432, "kamba_gate8"),
        )

    def test_o_nome_da_base_nao_tem_omissao(self) -> None:
        """Uma omissao `kamba_platform` punha o gate 8 a um esquecimento da base real."""
        with self.assertRaises(ligacao.ConfiguracaoEmFalta) as capturado:
            ligacao.alvo({})
        self.assertIn("KAMBA_DB_NAME", str(capturado.exception))

    def test_porta_que_nao_e_numero(self) -> None:
        with self.assertRaises(ligacao.ConfiguracaoEmFalta):
            ligacao.alvo({"KAMBA_DB_NAME": "x_gate8", "KAMBA_DB_PORT": "cinco"})


class TestCredenciais(unittest.TestCase):
    def test_cada_identidade_tem_o_seu_papel(self) -> None:
        self.assertEqual(ligacao.credenciais("admin", COMPLETO), ("kamba", "valor-admin"))
        self.assertEqual(
            ligacao.credenciais("migrator", COMPLETO), ("kamba_migrator", "valor-migrator")
        )
        self.assertEqual(ligacao.credenciais("app", COMPLETO), ("kamba_app", "valor-app"))
        self.assertEqual(
            ligacao.credenciais("batch", COMPLETO), ("kamba_batch", "valor-batch")
        )

    def test_identidade_desconhecida(self) -> None:
        with self.assertRaises(ValueError):
            ligacao.credenciais("ops", COMPLETO)

    def test_variavel_em_falta_nomeia_a_variavel_e_nunca_um_valor(self) -> None:
        for identidade, variavel in ligacao.VARIAVEL_DA_SENHA.items():
            with self.subTest(identidade=identidade):
                ambiente = {k: v for k, v in COMPLETO.items() if k != variavel}
                with self.assertRaises(ligacao.ConfiguracaoEmFalta) as capturado:
                    ligacao.credenciais(identidade, ambiente)
                mensagem = str(capturado.exception)
                self.assertIn(variavel, mensagem)
                for valor in COMPLETO.values():
                    if valor.startswith("valor-"):
                        self.assertNotIn(valor, mensagem)

    def test_palavra_passe_vazia_conta_como_em_falta(self) -> None:
        ambiente = dict(COMPLETO, KAMBA_SECRET_DB_APP_PASSWORD="")
        with self.assertRaises(ligacao.ConfiguracaoEmFalta):
            ligacao.credenciais("app", ambiente)

    def test_os_nomes_das_variaveis_sao_os_do_inventario_de_segredos(self) -> None:
        """`KAMBA_SECRET_` + id do inventario do KAM-010, em maiusculas."""
        self.assertEqual(
            {v for k, v in ligacao.VARIAVEL_DA_SENHA.items() if k != "admin"},
            {
                "KAMBA_SECRET_DB_MIGRATOR_PASSWORD",
                "KAMBA_SECRET_DB_APP_PASSWORD",
                "KAMBA_SECRET_DB_BATCH_PASSWORD",
                "KAMBA_SECRET_DB_RESOLVER_PASSWORD",
                "KAMBA_SECRET_DB_IDENTITY_PASSWORD",
                "KAMBA_SECRET_DB_AUDIT_PASSWORD",
                # KAM-026: o papel do checkpointer, o setimo.
                "KAMBA_SECRET_DB_AGR_PASSWORD",
            },
        )


class TestUrl(unittest.TestCase):
    def test_forma(self) -> None:
        self.assertEqual(
            ligacao.url_sqlalchemy("migrator", COMPLETO),
            "postgresql+pg8000://kamba_migrator:valor-migrator@127.0.0.1:5432/kamba_gate8",
        )

    def test_caracteres_especiais_na_palavra_passe_sao_codificados(self) -> None:
        """Um `@` ou `/` por codificar mudava o host a que o URL aponta."""
        ambiente = dict(COMPLETO, KAMBA_SECRET_DB_MIGRATOR_PASSWORD="a@b/c:d#e")
        url = ligacao.url_sqlalchemy("migrator", ambiente)
        self.assertIn("a%40b%2Fc%3Ad%23e@127.0.0.1", url)
        self.assertEqual(url.count("@"), 1)


if __name__ == "__main__":
    unittest.main()
