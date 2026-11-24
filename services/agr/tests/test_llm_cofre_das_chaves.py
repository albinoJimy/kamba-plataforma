"""De onde o AGR lê as chaves virtuais (KAM-250, critério 4).

**Canário:** `test_em_prod_sem_token_nao_le_do_ambiente`. Um leitor que caísse
para o ambiente quando falta o *token* passava todos os outros ensaios — e
reabria a via que o KAM-250 fecha: uma chave posta à mão no compose por cima do
projecto que o fundador escolheu.
"""

from __future__ import annotations

import json
import unittest

from kamba_core.secrets import EnvSecretProvider, RespostaHttp, SecretAusenteError, Secrets

from kamba_agr.llm.cofre_das_chaves import (
    INTERVALO_DO_REFRESCO_S,
    REF_DO_TOKEN_DE_LEITURA,
    leitor_das_chaves,
)

TENANT = "11111111-1111-4111-8111-111111111111"
NOME_DO_TENANT = "KAMBA_SECRET_LITELLM_VIRTUAL_KEY__" + TENANT.replace("-", "_")


def _segredos(ambiente: str, env: dict[str, str]) -> Secrets:
    return Secrets(servico="agr", provider=EnvSecretProvider(ambiente, env), obrigatorios=())


class _Doppler:
    """O projecto das chaves: devolve o que tem, e grava os pedidos."""

    def __init__(self) -> None:
        self.conteudo: dict[str, str] = {}
        self.pedidos: list[tuple[str, dict[str, str]]] = []

    def __call__(self, url, cabecalhos):
        self.pedidos.append((url, dict(cabecalhos)))
        return RespostaHttp(200, json.dumps(self.conteudo))


class _Relogio:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


class TestOsTresCaminhos(unittest.TestCase):
    def test_em_dev_le_do_ambiente(self) -> None:
        segredos = _segredos("dev", {NOME_DO_TENANT: "sk-de-dev"})
        ler, motivo = leitor_das_chaves("dev", segredos, servico="agr", transporte=_Doppler())
        self.assertEqual(ler(f"litellm_virtual_key/{TENANT}"), "sk-de-dev")
        self.assertEqual(motivo, "chaves_do_ambiente_em_dev")

    def test_em_prod_sem_token_nao_le_do_ambiente(self) -> None:
        doppler = _Doppler()
        segredos = _segredos(
            "prod",
            {NOME_DO_TENANT: "sk-posta-a-mao", "KAMBA_SECRET_LITELLM_SCREENING_KEY": "sk-velha"},
        )
        for ambiente in ("staging", "prod"):
            with self.subTest(ambiente=ambiente):
                ler, motivo = leitor_das_chaves(
                    ambiente, segredos, servico="agr", transporte=doppler
                )
                self.assertEqual(motivo, "chaves_sem_token_de_leitura")
                for ref in (f"litellm_virtual_key/{TENANT}", "litellm_screening_key"):
                    with self.assertRaises(SecretAusenteError):
                        ler(ref)
        self.assertEqual(doppler.pedidos, [])

    def test_em_prod_com_token_le_do_projecto_das_chaves(self) -> None:
        doppler = _Doppler()
        doppler.conteudo = {
            NOME_DO_TENANT: "sk-do-projecto",
            "KAMBA_SECRET_LITELLM_SCREENING_KEY": "sk-do-screening",
        }
        segredos = _segredos(
            "prod",
            {"KAMBA_SECRET_DOPPLER_LLM_CHAVES_LEITURA": "dp.st.leitura", NOME_DO_TENANT: "sk-env"},
        )
        ler, motivo = leitor_das_chaves(
            "prod", segredos, servico="agr",
            ambiente_do_processo={"KAMBA_LLM_CHAVES_PROJECTO": "projecto-de-ensaio"},
            transporte=doppler,
        )
        self.assertEqual(motivo, "chaves_do_projecto_proprio")
        self.assertEqual(ler(f"litellm_virtual_key/{TENANT}"), "sk-do-projecto")
        self.assertEqual(ler("litellm_screening_key"), "sk-do-screening")
        url, cabecalhos = doppler.pedidos[0]
        self.assertIn("project=projecto-de-ensaio", url)
        self.assertIn("config=prod", url)
        self.assertEqual(cabecalhos["authorization"], "Bearer dp.st.leitura")

    def test_o_token_de_leitura_e_o_do_inventario(self) -> None:
        self.assertEqual(REF_DO_TOKEN_DE_LEITURA, "doppler_llm_chaves_leitura")

    def test_o_projecto_por_omissao(self) -> None:
        doppler = _Doppler()
        segredos = _segredos("staging", {"KAMBA_SECRET_DOPPLER_LLM_CHAVES_LEITURA": "t"})
        ler, _ = leitor_das_chaves(
            "staging", segredos, servico="agr", ambiente_do_processo={}, transporte=doppler
        )
        with self.assertRaises(SecretAusenteError):
            ler("litellm_screening_key")
        self.assertIn("project=kamba-llm-chaves", doppler.pedidos[0][0])


class TestAChaveQueAcabouDeNascer(unittest.TestCase):
    """Uma ausência pede descarga nova, no máximo uma por intervalo."""

    def montar(self):
        doppler = _Doppler()
        relogio = _Relogio()
        segredos = _segredos("prod", {"KAMBA_SECRET_DOPPLER_LLM_CHAVES_LEITURA": "t"})
        ler, _ = leitor_das_chaves(
            "prod", segredos, servico="agr", ambiente_do_processo={},
            transporte=doppler, agora=relogio,
        )
        return doppler, relogio, ler

    def test_uma_chave_gravada_depois_da_descarga_le_se_sem_esperar_pela_cache(self) -> None:
        doppler, relogio, ler = self.montar()
        doppler.conteudo = {"KAMBA_SECRET_LITELLM_SCREENING_KEY": "sk-s"}
        self.assertEqual(ler("litellm_screening_key"), "sk-s")
        doppler.conteudo[NOME_DO_TENANT] = "sk-nasceu-agora"
        relogio.t += 1
        self.assertEqual(ler(f"litellm_virtual_key/{TENANT}"), "sk-nasceu-agora")

    def test_um_tenant_sem_chave_nao_poe_o_agr_a_bater_no_doppler(self) -> None:
        doppler, relogio, ler = self.montar()
        for _ in range(20):
            with self.assertRaises(SecretAusenteError):
                ler(f"litellm_virtual_key/{TENANT}")
            relogio.t += 0.1
        # A descarga guardada e uma descarga nova: duas, e não vinte.
        self.assertEqual(len(doppler.pedidos), 2)
        relogio.t += INTERVALO_DO_REFRESCO_S
        with self.assertRaises(SecretAusenteError):
            ler(f"litellm_virtual_key/{TENANT}")
        self.assertEqual(len(doppler.pedidos), 3)


class TestALigacaoNoArranque(unittest.TestCase):
    """O `__main__` liga as **duas** chaves ao leitor, e não ao `segredos.get`.

    Uma função certa ligada ao sítio errado passa todos os ensaios dela: sem este,
    trocar o `ler_chave` por `segredos.get` num dos dois `ClienteDeLlm` deixava a
    chave desse papel a ler-se do ambiente, onde em `prod` ela não existe.
    """

    def setUp(self) -> None:
        import ast
        import pathlib

        # Pelo caminho e não pelo `import`: importar o `__main__` custa 30 s.
        fonte = pathlib.Path(__file__).resolve().parents[1] / "src" / "kamba_agr" / "__main__.py"
        self.arvore = ast.parse(fonte.read_text(encoding="utf-8"))

    def test_as_duas_chaves_le_as_o_leitor(self) -> None:
        import ast

        valores = [
            k.value
            for no in ast.walk(self.arvore)
            if isinstance(no, ast.Call)
            for k in no.keywords
            if k.arg == "chave_virtual"
        ]
        self.assertEqual(len(valores), 2, "o do tenant e o do screening")
        for valor in valores:
            self.assertIsInstance(valor, ast.Lambda)
            self.assertIsInstance(valor.body, ast.Call)
            self.assertEqual(ast.unparse(valor.body.func), "ler_chave")

    def test_o_leitor_vem_do_cofre_das_chaves(self) -> None:
        import ast

        atribuicoes = [
            no
            for no in ast.walk(self.arvore)
            if isinstance(no, ast.Assign)
            and isinstance(no.value, ast.Call)
            and ast.unparse(no.value.func) == "leitor_das_chaves"
        ]
        self.assertEqual(len(atribuicoes), 1)
        self.assertEqual(
            ast.unparse(atribuicoes[0].targets[0]), "(ler_chave, motivo_das_chaves)"
        )
        self.assertEqual(
            [ast.unparse(a) for a in atribuicoes[0].value.args], ["ambiente", "segredos"]
        )


if __name__ == "__main__":
    unittest.main()
