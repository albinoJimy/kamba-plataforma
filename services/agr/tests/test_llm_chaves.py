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

import hashlib
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


class _Cofre:
    """Um duplo do cofre das chaves (KAM-250): um mapa, e a ordem das operações."""

    def __init__(self, registo: list[str] | None = None) -> None:
        self.segredos: dict[str, str] = {}
        self.escritas = 0
        self.registo = registo if registo is not None else []
        self.falhar = False

    def ler(self, ref: str) -> str | None:
        return self.segredos.get(ref)

    def gravar(self, ref: str, valor: str) -> None:
        if self.falhar:
            raise chaves.ErroDeProvisionamento("cofre inacessivel (provedor doppler): HTTP 503")
        self.escritas += 1
        self.registo.append(f"gravar:{ref}")
        self.segredos[ref] = valor


class _Proxy:
    """Um duplo da API de administração que **grava** o que recebeu.

    Como a imagem medida no KAM-250: o `/key/generate` usa o `key` do corpo, e o
    `token` que o `/key/list` devolve é o SHA-256 dele.
    """

    def __init__(self, existentes: list[dict[str, Any]] | None = None) -> None:
        self.chaves = list(existentes or [])
        self.pedidos: list[tuple[str, str, dict[str, Any] | None]] = []
        #: O proxy responde 200 ao `/key/delete` e nao apaga nada.
        self.delete_finge = False
        self.registo: list[str] = []
        self.cofre = _Cofre(self.registo)

    def __call__(self, url: str, metodo: str, chave: str, corpo: dict | None):
        self.pedidos.append((url, metodo, corpo))
        self.registo.append(url.rsplit("/", 1)[-1].split("?")[0])
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
            valor = corpo.get("key")
            if not isinstance(valor, str) or not valor.startswith("sk-"):
                # A forma medida: ecoa quatro caracteres de cada ponta.
                return 400, {"error": {"message": f"Invalid key format. Received: {str(valor)[:4]}****{str(valor)[-4:]}"}}
            token = hashlib.sha256(valor.encode()).hexdigest()
            guardada = {k: v for k, v in corpo.items() if k != "key"}
            self.chaves.append({**guardada, "spend": 0.0, "token": token})
            return 200, {**corpo, "spend": 0.0, "token": token}
        if url.endswith("/key/update"):
            for existente in self.chaves:
                if existente.get("key_alias") == corpo["key_alias"]:
                    existente.update(corpo)
                    return 200, dict(existente)
            return 404, {"error": {"message": "Key not found"}}
        if url.endswith("/key/delete"):
            # Le o corpo: so sai a chave cujo `token` vem em `keys`.
            antes = len(self.chaves)
            if not self.delete_finge:
                self.chaves = [k for k in self.chaves if k.get("token") not in corpo["keys"]]
            return (200, {"deleted_keys": corpo["keys"]}) if len(self.chaves) < antes or self.delete_finge else (
                404, {"error": {"message": "key not found"}})
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
            chaves.provisionar(duplo.proxy(), TENANT, "basico", AMBIENTE, cofre=duplo.cofre), "criada"
        )
        self.assertIn("generate", duplo.rotas())
        self.assertNotIn("update", duplo.rotas())

    def test_a_segunda_corrida_actualiza_e_nao_gera(self) -> None:
        """O canário: um `provisionar` que gerasse sempre devolvia 400 aqui."""
        duplo = _Proxy()
        chaves.provisionar(duplo.proxy(), TENANT, "basico", AMBIENTE, cofre=duplo.cofre)
        duplo.pedidos.clear()
        self.assertEqual(
            chaves.provisionar(duplo.proxy(), TENANT, "basico", AMBIENTE, cofre=duplo.cofre), "actualizada"
        )
        self.assertIn("update", duplo.rotas())
        self.assertNotIn("generate", duplo.rotas())

    def test_tres_corridas_deixam_uma_chave_so(self) -> None:
        duplo = _Proxy()
        for _ in range(3):
            chaves.provisionar(duplo.proxy(), TENANT, "basico", AMBIENTE, cofre=duplo.cofre)
        self.assertEqual(len(duplo.chaves), 1)

    def test_o_alias_e_o_do_131(self) -> None:
        self.assertEqual(chaves.alias_do_tenant(TENANT), f"tenant-{TENANT}")

    def test_os_metadados_levam_tenant_e_plano(self) -> None:
        duplo = _Proxy()
        chaves.provisionar(duplo.proxy(), TENANT, "basico", AMBIENTE, cofre=duplo.cofre)
        corpo = [c for u, _, c in duplo.pedidos if u.endswith("/key/generate")][0]
        self.assertEqual(corpo["metadata"], {"tenant_id": TENANT, "plano": "basico"})
        self.assertEqual(corpo["max_budget"], 1.5)
        self.assertEqual(corpo["budget_duration"], "30d")

    def test_a_chave_so_pode_chamar_os_papeis_do_agr(self) -> None:
        """`vision` e `embed` correm no COM e no IDX, não num turno de conversa."""
        duplo = _Proxy()
        chaves.provisionar(duplo.proxy(), TENANT, "basico", AMBIENTE, cofre=duplo.cofre)
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
        chaves.provisionar(duplo.proxy(), TENANT, "basico", AMBIENTE, cofre=duplo.cofre)
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
            chaves.provisionar(duplo.proxy(), TENANT, "ouro", AMBIENTE, cofre=duplo.cofre)
        self.assertEqual(duplo.chaves, [])


class TestAChaveDoScreening(unittest.TestCase):
    """A chave da plataforma do classificador de screening (KAM-195).

    Canário: `test_so_alcanca_o_screening_nano`. Uma chave do screening que
    alcançasse o `kamba-chat` dava a quem a tivesse uma conversa paga pela
    plataforma, fora do orçamento de qualquer *tenant*.
    """

    AMBIENTE = {"KAMBA_LLM_ORCAMENTO_USD_SCREENING": "5"}

    def test_so_alcanca_o_screening_nano(self) -> None:
        duplo = _Proxy()
        chaves.provisionar_screening(duplo.proxy(), self.AMBIENTE, cofre=duplo.cofre)
        corpo = [c for u, _, c in duplo.pedidos if u.endswith("/key/generate")][0]
        self.assertEqual(corpo["models"], ["screening-nano"])
        self.assertEqual(corpo["key_alias"], "plataforma-screening")
        self.assertEqual(corpo["max_budget"], 5.0)
        self.assertNotIn("tenant_id", corpo["metadata"])

    def test_e_idempotente(self) -> None:
        duplo = _Proxy()
        self.assertEqual(chaves.provisionar_screening(duplo.proxy(), self.AMBIENTE, cofre=duplo.cofre), "criada")
        self.assertEqual(chaves.provisionar_screening(duplo.proxy(), self.AMBIENTE, cofre=duplo.cofre), "actualizada")
        self.assertEqual(len(duplo.chaves), 1)

    def test_sem_orcamento_nao_cria_chave_nenhuma(self) -> None:
        for ambiente in ({}, {"KAMBA_LLM_ORCAMENTO_USD_SCREENING": "x"},
                         {"KAMBA_LLM_ORCAMENTO_USD_SCREENING": "0"},
                         {"KAMBA_LLM_ORCAMENTO_USD_SCREENING": "nan"},
                         {"KAMBA_LLM_ORCAMENTO_USD_SCREENING": "inf"}):
            with self.subTest(ambiente=ambiente):
                duplo = _Proxy()
                with self.assertRaises(chaves.ErroDeProvisionamento):
                    chaves.provisionar_screening(duplo.proxy(), ambiente, cofre=duplo.cofre)
                self.assertEqual(duplo.chaves, [])

    def test_o_grupo_e_o_que_o_gerador_produz_para_o_papel(self) -> None:
        import importlib.util
        import sys

        raiz = pathlib.Path(__file__).resolve().parents[3]
        ferramentas = str(raiz / "tools")
        if ferramentas not in sys.path:
            sys.path.insert(0, ferramentas)
        spec = importlib.util.spec_from_file_location(
            "llm_config_para_chaves_do_screening", raiz / "tools" / "llm_config" / "__init__.py"
        )
        gerador = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gerador)
        dados = gerador.ler(raiz)
        de_papel = {str(a["nome"]): str(a["papel"]) for a in dados["aliases"]}
        esperados = {
            gerador.nome_do_grupo(str(f["alias"]), int(f["ordem"]))
            for f in dados["fornecedores"]
            if de_papel[str(f["alias"])] == "screening"
        }
        self.assertEqual(set(chaves.MODELOS_DA_CHAVE_DO_SCREENING), esperados)


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
                chaves.provisionar(duplo.proxy(), TENANT, "basico", AMBIENTE, cofre=duplo.cofre)
                print(f"chave virtual criada: {chaves.alias_do_tenant(TENANT)}")
        finally:
            os.environ.clear()
            os.environ.update(antes)
        texto = saida.getvalue()
        valor = duplo.cofre.segredos[chaves.ref_do_tenant(TENANT)]
        self.assertNotIn(valor, texto)
        self.assertNotIn("sk-master", texto)
        self.assertIn("tenant-", texto)



class TestARevogacao(unittest.TestCase):
    """KAM-218: a chave de um tenant encerrado, criada a mao, sai pelo alias."""

    OUTRO = "22222222-2222-2222-2222-222222222222"

    def proxy_com_duas(self) -> _Proxy:
        return _Proxy([
            {"key_alias": chaves.alias_do_tenant(TENANT), "token": "hash-a", "spend": 0.0},
            {"key_alias": chaves.alias_do_tenant(self.OUTRO), "token": "hash-b", "spend": 0.0},
        ])

    def test_revoga_so_a_chave_do_tenant_pelo_token_e_confirma_pela_listagem(self) -> None:
        p = self.proxy_com_duas()
        self.assertEqual(chaves.revogar(p.proxy(), TENANT), "revogada")
        apagados = [c for u, m, c in p.pedidos if u.endswith("/key/delete")]
        self.assertEqual(apagados, [{"keys": ["hash-a"]}])
        self.assertEqual([k["key_alias"] for k in p.chaves], [chaves.alias_do_tenant(self.OUTRO)])
        self.assertEqual(p.rotas()[-1], "list", "a revogacao confirma-se pela listagem")

    def test_repetir_e_o_sucesso_de_uma_repeticao(self) -> None:
        p = self.proxy_com_duas()
        chaves.revogar(p.proxy(), TENANT)
        self.assertEqual(chaves.revogar(p.proxy(), TENANT), "inexistente")
        self.assertEqual(sum(1 for u, _, _ in p.pedidos if u.endswith("/key/delete")), 1)

    def test_um_200_com_a_chave_ainda_la_levanta(self) -> None:
        p = self.proxy_com_duas()
        p.delete_finge = True
        with self.assertRaises(chaves.ErroDeProvisionamento):
            chaves.revogar(p.proxy(), TENANT)

    def test_o_comando_diz_o_desfecho_e_nao_o_token(self) -> None:
        import contextlib
        import io

        p = self.proxy_com_duas()
        original = chaves._proxy_do_ambiente
        chaves._proxy_do_ambiente = p.proxy
        saida = io.StringIO()
        try:
            with contextlib.redirect_stdout(saida):
                self.assertEqual(chaves.main(["revogar", TENANT]), 0)
        finally:
            chaves._proxy_do_ambiente = original
        self.assertIn("revogada", saida.getvalue())
        self.assertNotIn("hash-a", saida.getvalue())


class TestOValorVaiParaOCofre(unittest.TestCase):
    """KAM-250: o valor que o proxy usa chega ao cofre, e só ao cofre.

    **Canário:** `test_a_segunda_corrida_nao_reemite_e_o_cofre_continua_a_autenticar`.
    Um `_garantir` que gerasse valor novo a cada corrida passava todos os ensaios
    de «grava no cofre» e partia o critério 3: a chave antiga deixava de valer a
    cada provisionamento.
    """

    def ref(self) -> str:
        return chaves.ref_do_tenant(TENANT)

    def test_a_referencia_e_a_do_inventario(self) -> None:
        self.assertEqual(self.ref(), f"litellm_virtual_key/{TENANT}")
        self.assertEqual(chaves.REF_DA_CHAVE_DO_SCREENING, "litellm_screening_key")

    def test_o_valor_do_generate_e_o_que_ficou_no_cofre(self) -> None:
        duplo = _Proxy()
        chaves.provisionar(duplo.proxy(), TENANT, "basico", AMBIENTE, cofre=duplo.cofre)
        corpo = [c for u, _, c in duplo.pedidos if u.endswith("/key/generate")][0]
        valor = duplo.cofre.segredos[self.ref()]
        self.assertEqual(corpo["key"], valor)
        self.assertTrue(valor.startswith("sk-"))
        self.assertEqual(duplo.chaves[0]["token"], chaves.resumo_da_chave(valor))

    def test_o_cofre_e_escrito_antes_do_proxy(self) -> None:
        """Uma queda entre os dois deixa um valor sem chave, e nunca uma chave sem valor."""
        duplo = _Proxy()
        chaves.provisionar(duplo.proxy(), TENANT, "basico", AMBIENTE, cofre=duplo.cofre)
        self.assertLess(
            duplo.registo.index(f"gravar:{self.ref()}"), duplo.registo.index("generate")
        )

    def test_sem_cofre_nao_se_cria_chave_nenhuma(self) -> None:
        duplo = _Proxy()
        duplo.cofre.falhar = True
        with self.assertRaises(chaves.ErroDeProvisionamento):
            chaves.provisionar(duplo.proxy(), TENANT, "basico", AMBIENTE, cofre=duplo.cofre)
        self.assertNotIn("generate", duplo.rotas())
        self.assertEqual(duplo.chaves, [])

    def test_a_segunda_corrida_nao_reemite_e_o_cofre_continua_a_autenticar(self) -> None:
        duplo = _Proxy()
        chaves.provisionar(duplo.proxy(), TENANT, "basico", AMBIENTE, cofre=duplo.cofre)
        antes = duplo.cofre.segredos[self.ref()]
        duplo.pedidos.clear()
        for _ in range(2):
            self.assertEqual(
                chaves.provisionar(duplo.proxy(), TENANT, "basico", AMBIENTE, cofre=duplo.cofre),
                "actualizada",
            )
        self.assertEqual(duplo.cofre.escritas, 1)
        self.assertEqual(duplo.cofre.segredos[self.ref()], antes)
        self.assertNotIn("generate", duplo.rotas())
        self.assertNotIn("delete", duplo.rotas())
        self.assertEqual(duplo.chaves[0]["token"], chaves.resumo_da_chave(antes))

    def test_uma_queda_depois_do_cofre_retoma_com_o_valor_que_la_esta(self) -> None:
        """O valor está no cofre e a chave não está no proxy: cria-se com ele, sem gravar outro."""
        duplo = _Proxy()
        duplo.cofre.segredos[self.ref()] = "sk-ja-no-cofre"
        self.assertEqual(
            chaves.provisionar(duplo.proxy(), TENANT, "basico", AMBIENTE, cofre=duplo.cofre),
            "criada",
        )
        self.assertEqual(duplo.cofre.escritas, 0)
        self.assertEqual(
            duplo.chaves[0]["token"],
            chaves.resumo_da_chave("sk-ja-no-cofre"),
        )

    def test_uma_chave_que_o_cofre_nao_autentica_e_reemitida(self) -> None:
        """A chave anterior ao KAM-250: está no proxy, e o valor não está em lado nenhum."""
        duplo = _Proxy([
            {"key_alias": chaves.alias_do_tenant(TENANT), "token": "resumo-de-um-valor-perdido",
             "spend": 0.0},
        ])
        self.assertEqual(
            chaves.provisionar(duplo.proxy(), TENANT, "basico", AMBIENTE, cofre=duplo.cofre),
            "reemitida",
        )
        apagados = [c for u, _, c in duplo.pedidos if u.endswith("/key/delete")]
        self.assertEqual(apagados, [{"keys": ["resumo-de-um-valor-perdido"]}])
        self.assertEqual(len(duplo.chaves), 1)
        self.assertEqual(
            duplo.chaves[0]["token"],
            chaves.resumo_da_chave(duplo.cofre.segredos[self.ref()]),
        )

    def test_um_valor_no_cofre_que_nao_bate_reemite_com_esse_valor(self) -> None:
        duplo = _Proxy([
            {"key_alias": chaves.alias_do_tenant(TENANT), "token": "outro", "spend": 0.0},
        ])
        duplo.cofre.segredos[self.ref()] = "sk-o-do-cofre"
        self.assertEqual(
            chaves.provisionar(duplo.proxy(), TENANT, "basico", AMBIENTE, cofre=duplo.cofre),
            "reemitida",
        )
        self.assertEqual(duplo.cofre.escritas, 0)
        self.assertEqual(duplo.chaves[0]["token"], chaves.resumo_da_chave("sk-o-do-cofre"))

    def test_a_corrida_concorrente_converge_para_o_valor_do_cofre(self) -> None:
        """O 400 «already exists»: outra corrida criou a chave com outro valor no meio desta."""
        duplo = _Proxy()
        outra = "sk-da-outra-corrida"

        def concorrente(url, metodo, chave, corpo):
            if url.endswith("/key/generate") and not duplo.chaves:
                # A outra corrida chega primeiro: cria a chave e reescreve o cofre.
                duplo(url, metodo, chave, {**corpo, "key": outra})
                duplo.cofre.segredos[self.ref()] = outra
            return duplo(url, metodo, chave, corpo)

        proxy = chaves.Proxy("http://litellm:4000", "sk-master", pedir=concorrente)
        chaves.provisionar(proxy, TENANT, "basico", AMBIENTE, cofre=duplo.cofre)
        self.assertEqual(len(duplo.chaves), 1)
        self.assertEqual(
            duplo.chaves[0]["token"],
            chaves.resumo_da_chave(duplo.cofre.segredos[self.ref()]),
        )

    def test_o_screening_grava_na_referencia_dele(self) -> None:
        duplo = _Proxy()
        chaves.provisionar_screening(
            duplo.proxy(), {"KAMBA_LLM_ORCAMENTO_USD_SCREENING": "5"}, cofre=duplo.cofre
        )
        self.assertEqual(list(duplo.cofre.segredos), ["litellm_screening_key"])
        self.assertEqual(
            duplo.chaves[0]["token"],
            chaves.resumo_da_chave(duplo.cofre.segredos["litellm_screening_key"]),
        )

    def test_o_erro_do_generate_nao_cita_o_corpo(self) -> None:
        """Medido: o 400 de uma chave mal formada ecoa oito caracteres dela."""
        def mal(url, metodo, chave, corpo):
            if url.endswith("/key/generate"):
                valor = corpo["key"]
                return 400, {"error": {"message": f"Received: {valor[:4]}****{valor[-4:]}"}}
            return 200, {"keys": [], "total_count": 0}

        proxy = chaves.Proxy("http://litellm:4000", "sk-master", pedir=mal)
        cofre = _Cofre()
        with self.assertRaises(chaves.ErroDeProvisionamento) as apanhado:
            chaves.provisionar(proxy, TENANT, "basico", AMBIENTE, cofre=cofre)
        valor = cofre.segredos[self.ref()]
        self.assertNotIn(valor[:4] + "****", str(apanhado.exception))
        self.assertNotIn(valor[-4:], str(apanhado.exception))


class TestOComandoComOCofre(unittest.TestCase):
    """O `main`: recusa sem cofre antes do proxy, e nada do valor no `stdout`/`stderr`."""

    def correr(self, argv, ambiente, proxy=None, cofre=None):
        import contextlib
        import io
        import os

        saida, erros = io.StringIO(), io.StringIO()
        antes = dict(os.environ)
        originais = (chaves._proxy_do_ambiente, chaves._cofre_do_ambiente)
        if proxy is not None:
            chaves._proxy_do_ambiente = proxy
        if cofre is not None:
            chaves._cofre_do_ambiente = cofre
        os.environ.clear()
        os.environ.update(ambiente)
        try:
            with contextlib.redirect_stdout(saida), contextlib.redirect_stderr(erros):
                codigo = chaves.main(argv)
        finally:
            os.environ.clear()
            os.environ.update(antes)
            chaves._proxy_do_ambiente, chaves._cofre_do_ambiente = originais
        return codigo, saida.getvalue(), erros.getvalue()

    def test_sem_token_de_escrita_recusa_antes_de_falar_com_o_proxy(self) -> None:
        duplo = _Proxy()
        codigo, _, erros = self.correr(
            ["provisionar", TENANT, "basico"],
            {"KAMBA_ENV": "prod", **AMBIENTE},
            proxy=duplo.proxy,
        )
        self.assertEqual(codigo, 2)
        self.assertIn("doppler_llm_chaves_escrita", erros)
        self.assertEqual(duplo.pedidos, [])

    def test_sem_ambiente_recusa(self) -> None:
        duplo = _Proxy()
        codigo, _, erros = self.correr(
            ["provisionar-screening"], {"KAMBA_SECRET_DOPPLER_LLM_CHAVES_ESCRITA": "dp.st.x"},
            proxy=duplo.proxy,
        )
        self.assertEqual(codigo, 2)
        self.assertIn("KAMBA_ENV", erros)
        self.assertEqual(duplo.pedidos, [])

    def test_o_valor_nao_sai_em_stdout_nem_stderr(self) -> None:
        duplo = _Proxy()
        for argv in (["provisionar", TENANT, "basico"], ["provisionar", TENANT, "basico"],
                     ["provisionar-screening"]):
            codigo, saida, erros = self.correr(
                argv,
                {**AMBIENTE, "KAMBA_LLM_ORCAMENTO_USD_SCREENING": "5"},
                proxy=duplo.proxy,
                cofre=lambda: duplo.cofre,
            )
            self.assertEqual(codigo, 0, erros)
            for valor in duplo.cofre.segredos.values():
                self.assertNotIn(valor, saida + erros)
                self.assertNotIn(chaves.resumo_da_chave(valor), saida + erros)
        self.assertEqual(len(duplo.cofre.segredos), 2)

    def test_o_cofre_doppler_le_e_grava_o_projecto_das_chaves(self) -> None:
        """O `CofreDoppler` contra um transporte que lê o texto do pedido."""
        import json

        from kamba_core.secrets import RespostaHttp

        pedidos: list[tuple[str, dict, bytes | None]] = []
        guardado: dict[str, str] = {}

        def ler(url, cabecalhos):
            pedidos.append((url, dict(cabecalhos), None))
            return RespostaHttp(200, json.dumps(guardado))

        def escrever(url, cabecalhos, corpo):
            pedidos.append((url, dict(cabecalhos), corpo))
            guardado.update(json.loads(corpo)["secrets"])
            return RespostaHttp(200, "{}")

        originais = (chaves.transporte_http_de_leitura, chaves.transporte_http_de_escrita)
        chaves.transporte_http_de_leitura, chaves.transporte_http_de_escrita = ler, escrever
        ref = chaves.ref_do_tenant(TENANT)
        try:
            cofre = chaves.CofreDoppler("prod", "kamba-llm-chaves", "dp.st.escrita")
            self.assertIsNone(cofre.ler(ref))
            cofre.gravar(ref, "sk-valor-de-ensaio")
            self.assertEqual(cofre.ler(ref), "sk-valor-de-ensaio")
        finally:
            chaves.transporte_http_de_leitura, chaves.transporte_http_de_escrita = originais
        url_escrita, cab, corpo = pedidos[1]
        self.assertTrue(url_escrita.endswith("/v3/configs/config/secrets"))
        self.assertEqual(cab["authorization"], "Bearer dp.st.escrita")
        enviado = json.loads(corpo)
        self.assertEqual(enviado["project"], "kamba-llm-chaves")
        self.assertEqual(enviado["config"], "prod")
        self.assertEqual(
            enviado["secrets"],
            {"KAMBA_SECRET_LITELLM_VIRTUAL_KEY__" + TENANT.replace("-", "_"): "sk-valor-de-ensaio"},
        )
        self.assertIn("project=kamba-llm-chaves", pedidos[2][0])


if __name__ == "__main__":
    unittest.main()
