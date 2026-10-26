"""O provisionamento de chaves virtuais e o alerta de orçamento (KAM-030, critério 4).

O código vive em `infra/llm/chaves.py`, fora de qualquer pacote instalado —
corre à mão na Fase 0, como o bloco manda. Carrega-se **pelo caminho**, como o
`test_ligacao.py` faz com o `db/ligacao.py`.

**O canário desta bateria** é `test_a_segunda_corrida_actualiza_e_nao_gera`: sem
ele, um `provisionar` que chamasse sempre `/key/generate` passava um teste de
«cria a chave» e devolvia **400** na segunda corrida — e o critério 4 diz que
criar a chave de um *tenant* é idempotente. Medido contra a versão fixada: o
`/key/generate` **não** é idempotente (`docs/evidencia/KAM-030-litellm.md`).
"""

from __future__ import annotations

import importlib.util
import pathlib
import unittest
from typing import Any


def _chaves():
    raiz = pathlib.Path(__file__).resolve().parents[3]
    spec = importlib.util.spec_from_file_location(
        "chaves_do_llm", raiz / "infra" / "llm" / "chaves.py"
    )
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


chaves = _chaves()

TENANT = "11111111-1111-1111-1111-111111111111"
AMBIENTE = {"KAMBA_LLM_MENSALIDADE_USD_BASICO": "10.00"}


class _Proxy:
    """Um duplo da API de administração que **grava** o que recebeu."""

    def __init__(self, existentes: list[dict[str, Any]] | None = None) -> None:
        self.chaves = list(existentes or [])
        self.pedidos: list[tuple[str, str, dict[str, Any] | None]] = []

    def __call__(self, url: str, metodo: str, chave: str, corpo: dict | None):
        self.pedidos.append((url, metodo, corpo))
        if "/key/list" in url:
            return 200, {"keys": self.chaves, "total_count": len(self.chaves)}
        if url.endswith("/key/generate"):
            if any(k.get("key_alias") == corpo["key_alias"] for k in self.chaves):
                # A forma medida contra a versão fixada.
                return 400, {
                    "error": {
                        "message": f"Key with alias '{corpo['key_alias']}' already exists.",
                        "type": "bad_request_error",
                    }
                }
            self.chaves.append({**corpo, "spend": 0.0, "key": "sk-nova"})
            return 200, {**corpo, "spend": 0.0, "key": "sk-nova"}
        if url.endswith("/key/update"):
            for existente in self.chaves:
                if existente.get("key_alias") == corpo["key_alias"]:
                    existente.update(corpo)
                    return 200, dict(existente)
            return 404, {"error": {"message": "Key not found"}}
        raise AssertionError(f"rota inesperada: {url}")

    def proxy(self) -> Any:
        return chaves.Proxy("http://litellm:4000", "sk-master", pedir=self)

    def rotas(self) -> list[str]:
        return [u.rsplit("/", 1)[-1].split("?")[0] for u, _, _ in self.pedidos]


class TestOOrcamento(unittest.TestCase):
    def test_sao_quinze_por_cento_da_mensalidade(self) -> None:
        self.assertEqual(chaves.orcamento_do_plano("basico", AMBIENTE), 1.5)

    def test_a_fraccao_e_a_do_1333(self) -> None:
        self.assertEqual(chaves.FRACCAO_DO_ORCAMENTO, 0.15)

    def test_sem_mensalidade_definida_levanta(self) -> None:
        """Um orçamento inventado é um tecto de custo que ninguém decidiu."""
        with self.assertRaises(chaves.ErroDeProvisionamento) as apanhado:
            chaves.orcamento_do_plano("basico", {})
        self.assertIn("H6", str(apanhado.exception))

    def test_uma_mensalidade_que_nao_e_numero_levanta(self) -> None:
        with self.assertRaises(chaves.ErroDeProvisionamento):
            chaves.orcamento_do_plano("basico", {"KAMBA_LLM_MENSALIDADE_USD_BASICO": "dez"})

    def test_uma_mensalidade_zero_levanta(self) -> None:
        with self.assertRaises(chaves.ErroDeProvisionamento):
            chaves.orcamento_do_plano("basico", {"KAMBA_LLM_MENSALIDADE_USD_BASICO": "0"})


class TestAIdempotencia(unittest.TestCase):
    """Critério 4: «criar uma chave virtual por tenant (…) é idempotente»."""

    def test_a_primeira_corrida_gera(self) -> None:
        duplo = _Proxy()
        self.assertEqual(
            chaves.provisionar(duplo.proxy(), TENANT, "basico", AMBIENTE), "criada"
        )
        self.assertIn("generate", duplo.rotas())
        self.assertNotIn("update", duplo.rotas())

    def test_a_segunda_corrida_actualiza_e_nao_gera(self) -> None:
        """O canário: um `provisionar` que gerasse sempre devolvia 400 aqui."""
        duplo = _Proxy()
        chaves.provisionar(duplo.proxy(), TENANT, "basico", AMBIENTE)
        duplo.pedidos.clear()
        self.assertEqual(
            chaves.provisionar(duplo.proxy(), TENANT, "basico", AMBIENTE), "actualizada"
        )
        self.assertIn("update", duplo.rotas())
        self.assertNotIn("generate", duplo.rotas())

    def test_tres_corridas_deixam_uma_chave_so(self) -> None:
        duplo = _Proxy()
        for _ in range(3):
            chaves.provisionar(duplo.proxy(), TENANT, "basico", AMBIENTE)
        self.assertEqual(len(duplo.chaves), 1)

    def test_o_alias_e_o_do_131(self) -> None:
        self.assertEqual(chaves.alias_do_tenant(TENANT), f"tenant-{TENANT}")

    def test_os_metadados_levam_tenant_e_plano(self) -> None:
        duplo = _Proxy()
        chaves.provisionar(duplo.proxy(), TENANT, "basico", AMBIENTE)
        corpo = [c for u, _, c in duplo.pedidos if u.endswith("/key/generate")][0]
        self.assertEqual(corpo["metadata"], {"tenant_id": TENANT, "plano": "basico"})
        self.assertEqual(corpo["max_budget"], 1.5)
        self.assertEqual(corpo["budget_duration"], "30d")

    def test_a_chave_so_pode_chamar_os_papeis_do_agr(self) -> None:
        """`vision` e `embed` correm no COM e no IDX, não num turno de conversa."""
        duplo = _Proxy()
        chaves.provisionar(duplo.proxy(), TENANT, "basico", AMBIENTE)
        corpo = [c for u, _, c in duplo.pedidos if u.endswith("/key/generate")][0]
        self.assertNotIn("kamba-vision", corpo["models"])
        self.assertNotIn("kamba-embed", corpo["models"])
        self.assertIn("kamba-router", corpo["models"])
        self.assertIn("kamba-chat", corpo["models"])

    def test_a_chave_autoriza_o_grupo_de_fallback(self) -> None:
        """O achado 11 da revisão adversarial, e fazia o critério 6 falhar em `staging`.

        O *fallback* é entre **grupos distintos** (`kamba-chat` →
        `kamba-chat-fallback2`), e não entre duas entradas do mesmo
        `model_name`. Sem o segundo grupo na *allowlist* da própria chave
        virtual, uma falha do primeiro fornecedor topava com ela — e as 20
        corridas que mediram o critério 6 foram feitas com `Router(...)` em
        Python, **sem chave virtual**, pelo que nada o apanhava.
        """
        duplo = _Proxy()
        chaves.provisionar(duplo.proxy(), TENANT, "basico", AMBIENTE)
        corpo = [c for u, _, c in duplo.pedidos if u.endswith("/key/generate")][0]
        self.assertIn("kamba-chat-fallback2", corpo["models"])

    def test_os_grupos_da_chave_sao_os_que_o_gerador_produz(self) -> None:
        """A máquina que impede a lista literal de divergir do `llm/aliases.yaml`.

        O `MODELOS_DA_CHAVE` é literal de propósito — este *script* corre à mão,
        fora de qualquer `.venv`, e derivá-lo punha-o a depender do leitor de
        YAML de `tools/`. O preço é este teste.
        """
        import importlib.util
        import sys

        raiz = pathlib.Path(__file__).resolve().parents[3]
        ferramentas = str(raiz / "tools")
        if ferramentas not in sys.path:
            sys.path.insert(0, ferramentas)
        spec = importlib.util.spec_from_file_location(
            "llm_config_para_chaves", raiz / "tools" / "llm_config" / "__init__.py"
        )
        gerador = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gerador)
        dados = gerador.ler(raiz)

        # Os grupos dos papéis que uma chave de *tenant* pode chamar.
        papeis_do_agr = {"router", "chat"}
        de_papel = {
            str(a["nome"]): str(a["papel"]) for a in dados["aliases"]
        }
        esperados = {
            gerador.nome_do_grupo(str(f["alias"]), int(f["ordem"]))
            for f in dados["fornecedores"]
            if de_papel[str(f["alias"])] in papeis_do_agr
        }
        self.assertEqual(set(chaves.MODELOS_DA_CHAVE), esperados)

    def test_um_plano_sem_mensalidade_nao_cria_chave_nenhuma(self) -> None:
        duplo = _Proxy()
        with self.assertRaises(chaves.ErroDeProvisionamento):
            chaves.provisionar(duplo.proxy(), TENANT, "ouro", AMBIENTE)
        self.assertEqual(duplo.chaves, [])


class TestOAlertaDos80(unittest.TestCase):
    """O «alertas a 80%» do §13.3."""

    def test_abaixo_do_limiar_nao_alerta(self) -> None:
        duplo = _Proxy([{"key_alias": "tenant-a", "spend": 1.0, "max_budget": 2.0}])
        self.assertEqual(chaves.orcamentos(duplo.proxy()), [])

    def test_exactamente_no_limiar_alerta(self) -> None:
        duplo = _Proxy([{"key_alias": "tenant-a", "spend": 1.6, "max_budget": 2.0}])
        self.assertEqual(chaves.orcamentos(duplo.proxy()), [("tenant-a", 1.6, 2.0)])

    def test_acima_do_limiar_alerta(self) -> None:
        duplo = _Proxy([{"key_alias": "tenant-a", "spend": 1.9, "max_budget": 2.0}])
        self.assertEqual(len(chaves.orcamentos(duplo.proxy())), 1)

    def test_o_limiar_e_80_por_cento(self) -> None:
        self.assertEqual(chaves.LIMIAR_DE_ALERTA, 0.80)

    def test_uma_chave_sem_tecto_nao_entra(self) -> None:
        """Sem tecto não há fracção; `0/0` como «100% gasto» era ruído."""
        duplo = _Proxy(
            [
                {"key_alias": "tenant-sem-tecto", "spend": 5.0, "max_budget": 0.0},
                {"key_alias": "tenant-nulo", "spend": 5.0, "max_budget": None},
            ]
        )
        self.assertEqual(chaves.orcamentos(duplo.proxy()), [])

    def test_varias_chaves_vem_ordenadas(self) -> None:
        duplo = _Proxy(
            [
                {"key_alias": "tenant-b", "spend": 1.9, "max_budget": 2.0},
                {"key_alias": "tenant-a", "spend": 1.9, "max_budget": 2.0},
            ]
        )
        self.assertEqual(
            [a for a, _, _ in chaves.orcamentos(duplo.proxy())], ["tenant-a", "tenant-b"]
        )


class TestOProxyExigeAMasterKey(unittest.TestCase):
    def test_sem_master_key_levanta(self) -> None:
        with self.assertRaises(chaves.ErroDeProvisionamento) as apanhado:
            chaves.Proxy("http://litellm:4000", "")
        self.assertIn("cofre", str(apanhado.exception))

    def test_um_key_list_que_falha_levanta(self) -> None:
        def falha(url, metodo, chave, corpo):
            return 500, {"error": {"message": "DB not connected"}}

        proxy = chaves.Proxy("http://litellm:4000", "sk-master", pedir=falha)
        with self.assertRaises(chaves.ErroDeProvisionamento) as apanhado:
            chaves.orcamentos(proxy)
        self.assertIn("500", str(apanhado.exception))


class TestOComandoNaoImprimeSegredos(unittest.TestCase):
    def test_o_valor_da_chave_nao_sai_no_stdout(self) -> None:
        """O `/key/generate` devolve a chave em claro; isto nunca a imprime."""
        import contextlib
        import io
        import os

        duplo = _Proxy()
        saida = io.StringIO()
        antes = dict(os.environ)
        os.environ.update(
            {
                "KAMBA_SECRET_LITELLM_MASTER_KEY": "sk-master",
                **AMBIENTE,
            }
        )
        try:
            with contextlib.redirect_stdout(saida):
                # O `main` monta o proxy do ambiente; aqui mede-se so o que sai
                # da funcao, com o duplo.
                chaves.provisionar(duplo.proxy(), TENANT, "basico", AMBIENTE)
                print(f"chave virtual criada: {chaves.alias_do_tenant(TENANT)}")
        finally:
            os.environ.clear()
            os.environ.update(antes)
        texto = saida.getvalue()
        self.assertNotIn("sk-nova", texto)
        self.assertNotIn("sk-master", texto)
        self.assertIn("tenant-", texto)


if __name__ == "__main__":
    unittest.main()
