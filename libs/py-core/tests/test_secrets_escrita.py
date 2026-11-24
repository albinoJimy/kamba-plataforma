"""A escrita numa referência fixa do cofre (KAM-250).

O duplo **lê o texto do pedido** — o URL, os cabeçalhos e o corpo —, como o bloco
do KAM-250 manda («a escrita no cofre contra um duplo que lê o texto do pedido»).
Um duplo que só contasse chamadas passava com o corpo vazio ou com a família
errada.

**Canário:** `test_recusa_uma_familia_que_nao_e_das_chaves`. Sem a lista de
famílias, este gravador escrevia qualquer segredo no projecto das chaves — e um
erro de programação que lhe passasse `meta_app_secret` punha o segredo da Meta
num sítio onde o AGR o lia.
"""

from __future__ import annotations

import json
import unittest

from kamba_core.secrets import (
    A_CONFIRMAR_ESCRITA,
    FAMILIAS_DAS_CHAVES_DO_LLM,
    AmbienteErradoError,
    CofreInacessivelError,
    DopplerGravador,
    FamiliaNaoGravavelError,
    GravadorDeSegredo,
    RespostaHttp,
    SecretRefInvalidaError,
)

TENANT = "11111111-1111-4111-8111-111111111111"
VALOR = "sk-valor-ensaio"


class _Transporte:
    def __init__(self, status: int = 200, corpo: str = "{}", levanta: Exception | None = None):
        self.pedidos: list[tuple[str, dict[str, str], bytes]] = []
        self.status = status
        self.corpo = corpo
        self.levanta = levanta

    def __call__(self, url, cabecalhos, corpo):
        self.pedidos.append((url, dict(cabecalhos), corpo))
        if self.levanta is not None:
            raise self.levanta
        return RespostaHttp(self.status, self.corpo)


def _gravador(transporte, **extra) -> DopplerGravador:
    return DopplerGravador(
        "prod", "kamba-llm-chaves", "prod", "dp.st.escrita", transporte, **extra
    )


class TestOPedido(unittest.TestCase):
    def test_implementa_a_porta(self) -> None:
        self.assertIsInstance(_gravador(_Transporte()), GravadorDeSegredo)

    def test_o_corpo_leva_o_projecto_a_config_e_o_nome_da_variavel(self) -> None:
        t = _Transporte()
        _gravador(t).gravar(f"litellm_virtual_key/{TENANT}", VALOR)
        url, cabecalhos, corpo = t.pedidos[0]
        self.assertEqual(url, "https://api.doppler.com/v3/configs/config/secrets")
        self.assertEqual(cabecalhos["authorization"], "Bearer dp.st.escrita")
        self.assertEqual(
            json.loads(corpo),
            {
                "project": "kamba-llm-chaves",
                "config": "prod",
                "secrets": {
                    "KAMBA_SECRET_LITELLM_VIRTUAL_KEY__" + TENANT.replace("-", "_"): VALOR
                },
            },
        )

    def test_o_nome_e_o_que_o_leitor_procura(self) -> None:
        """A escrita e a leitura usam o mesmo `nome_da_variavel`: o que se grava lê-se."""
        from kamba_core.secrets import DopplerSecretProvider

        t = _Transporte()
        _gravador(t).gravar("litellm_screening_key", VALOR)
        segredos = json.loads(t.pedidos[0][2])["secrets"]
        leitor = DopplerSecretProvider(
            "prod", "kamba-llm-chaves", "prod", "dp.st.leitura",
            lambda url, cab: RespostaHttp(200, json.dumps(segredos)),
        )
        self.assertEqual(leitor.get("litellm_screening_key"), VALOR)

    def test_a_forma_por_confirmar_esta_declarada(self) -> None:
        self.assertEqual(
            set(A_CONFIRMAR_ESCRITA), {"caminho", "corpo", "resposta", "limite_do_token"}
        )


class TestAsRecusas(unittest.TestCase):
    def test_recusa_uma_familia_que_nao_e_das_chaves(self) -> None:
        t = _Transporte()
        for ref in ("meta_app_secret", "litellm_master_key", "doppler_llm_chaves_leitura"):
            with self.subTest(ref=ref), self.assertRaises(FamiliaNaoGravavelError):
                _gravador(t).gravar(ref, VALOR)
        self.assertEqual(t.pedidos, [])

    def test_as_familias_sao_as_duas_chaves_virtuais(self) -> None:
        self.assertEqual(
            FAMILIAS_DAS_CHAVES_DO_LLM, ("litellm_virtual_key", "litellm_screening_key")
        )

    def test_recusa_uma_referencia_mal_formada_sem_a_citar(self) -> None:
        with self.assertRaises(SecretRefInvalidaError) as apanhado:
            _gravador(_Transporte()).gravar(VALOR, VALOR)
        self.assertNotIn(VALOR, str(apanhado.exception))

    def test_recusa_valor_vazio(self) -> None:
        t = _Transporte()
        with self.assertRaises(ValueError):
            _gravador(t).gravar("litellm_screening_key", "  ")
        self.assertEqual(t.pedidos, [])

    def test_config_de_outro_ambiente_recusa_construir(self) -> None:
        with self.assertRaises(AmbienteErradoError):
            DopplerGravador("prod", "kamba-llm-chaves", "staging", "dp.st.x", _Transporte())

    def test_sem_token_recusa_construir(self) -> None:
        with self.assertRaises(CofreInacessivelError):
            DopplerGravador("prod", "kamba-llm-chaves", "prod", " ", _Transporte())


class TestOValorNaoSaiNosErros(unittest.TestCase):
    """Regra 1 da porta: nenhuma mensagem de erro contém um valor de segredo."""

    def verificar(self, transporte) -> CofreInacessivelError:
        with self.assertRaises(CofreInacessivelError) as apanhado:
            _gravador(transporte).gravar("litellm_screening_key", VALOR)
        texto = str(apanhado.exception) + repr(apanhado.exception)
        self.assertNotIn(VALOR, texto)
        self.assertNotIn("dp.st.escrita", texto)
        self.assertIsNone(apanhado.exception.__cause__)
        return apanhado.exception

    def test_uma_falha_de_transporte_que_cita_o_corpo(self) -> None:
        erro = self.verificar(_Transporte(levanta=RuntimeError(f"falhou a enviar {VALOR}")))
        self.assertIn("RuntimeError", str(erro))

    def test_um_500_que_ecoa_o_pedido(self) -> None:
        erro = self.verificar(_Transporte(status=500, corpo=json.dumps({"eco": VALOR})))
        self.assertIn("500", str(erro))

    def test_um_403(self) -> None:
        erro = self.verificar(_Transporte(status=403, corpo=VALOR))
        self.assertIn("recusada", str(erro))


if __name__ == "__main__":
    unittest.main()
