"""As guardas do ADR-002 em *runtime* (criterios 7 e 8).

O que esta bateria prova: que a guarda **encontra** um `langgraph_api`
importavel, que nao o importa para o descobrir, e que a telemetria fica a
`false`. O que ela nao prova, e que ninguem pode provar com um teste: que o
egresso para `beacon.langchain.com` esta bloqueado na rede. Isso e o KAM-076; o
que este ticket tem e o contrato em `services/agr/egress.yaml`, e e esse que a
*suite* do *gate* 8 le.
"""

from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path

from kamba_agr.egresso import (
    BEACON,
    DISTRIBUICOES_PROIBIDAS,
    MODULOS_PROIBIDOS,
    TELEMETRIA_DESLIGADA,
    VARIAVEIS_DE_TELEMETRIA,
    ModuloProibidoError,
    desligar_telemetria,
    exigir_biblioteca_mit,
    exigir_sbom_mit,
    normalizar,
)

RAIZ = Path(__file__).resolve().parents[3]


class TestListaDeBloqueio(unittest.TestCase):
    def test_numa_arvore_sa_a_guarda_passa(self) -> None:
        exigir_biblioteca_mit()  # nao levanta

    def test_um_modulo_proibido_importavel_levanta(self) -> None:
        for proibido in MODULOS_PROIBIDOS:
            with self.subTest(modulo=proibido):
                modulo = types.ModuleType(proibido)
                modulo.__spec__ = types.SimpleNamespace(name=proibido)  # type: ignore[attr-defined]
                sys.modules[proibido] = modulo
                self.addCleanup(sys.modules.pop, proibido, None)
                with self.assertRaises(ModuloProibidoError) as apanhado:
                    exigir_biblioteca_mit()
                self.assertIn(proibido, str(apanhado.exception))
                self.assertIn(BEACON, str(apanhado.exception))
                sys.modules.pop(proibido, None)

    def test_a_guarda_nao_importa_o_modulo_para_o_descobrir(self) -> None:
        # Um `import` executava o `__init__.py` do pacote proibido — isto e,
        # corria o codigo que estamos a recusar.
        correu = {"sim": False}

        class EspiaDeImportacao:
            def find_module(self, *_args):  # pragma: no cover - API antiga
                return None

            def find_spec(self, nome, _caminho=None, _alvo=None):
                if nome in MODULOS_PROIBIDOS:
                    correu["sim"] = True
                return None

        espia = EspiaDeImportacao()
        sys.meta_path.insert(0, espia)
        self.addCleanup(sys.meta_path.remove, espia)
        exigir_biblioteca_mit()
        self.assertTrue(correu["sim"], "a guarda nem procurou o modulo")

    def test_os_nomes_sao_de_modulo_e_nao_de_distribuicao(self) -> None:
        # `langgraph-api` com hifen nunca e encontrado pelo `find_spec`: uma
        # guarda que passa sempre.
        for nome in MODULOS_PROIBIDOS:
            with self.subTest(nome=nome):
                self.assertNotIn("-", nome)

    def test_um_find_spec_que_levanta_conta_como_ausente(self) -> None:
        # Sem isto, a propria verificacao derrubava o arranque.
        marcador = f"{MODULOS_PROIBIDOS[0]}.subpacote"

        class EspiaQueLevanta:
            def find_spec(self, nome, _caminho=None, _alvo=None):
                if nome in MODULOS_PROIBIDOS:
                    raise ImportError("pai inexistente")
                return None

        espia = EspiaQueLevanta()
        sys.meta_path.insert(0, espia)
        self.addCleanup(sys.meta_path.remove, espia)
        exigir_biblioteca_mit()  # nao levanta
        self.assertTrue(marcador)


class TestSbomDoAmbiente(unittest.TestCase):
    """A segunda metade do criterio 7 (KAM-027): «ou constar do SBOM».

    O `find_spec` procura **modulos** e isto procura **distribuicoes
    instaladas**, e a diferenca mede-se num pacote real: o
    `langgraph-checkpoint-postgres` instala `langgraph.checkpoint.postgres`,
    dentro de um pacote de *namespace* que nos temos — nenhum nome de
    `MODULOS_PROIBIDOS` o encontraria, e ele e LGPL por transitividade.
    """

    def _instalada(self, nome: str, versao: str):
        """Finge uma distribuicao instalada, sem a instalar."""
        from unittest import mock

        class Falsa:
            metadata = {"Name": nome}
            version = versao

        return mock.patch(
            "kamba_agr.egresso.importlib.metadata.distributions", return_value=[Falsa()]
        )

    def test_o_fecho_declarado_do_agr_nao_tem_pacote_bloqueado(self) -> None:
        """Mede o **fecho do AGR**, e nao o interpretador que corre os testes.

        O nome anterior (`test_neste_ambiente_a_guarda_passa`) afirmava sobre
        tudo o que estivesse instalado — incluindo o que as ferramentas de
        desenvolvimento trazem —, e isso nao e o que o critero 7 pede nem o que
        a imagem do servico tem. Le-se o `runtime.txt`, que e o que o
        `Dockerfile` instala com `--require-hashes --no-deps`.
        """
        declarados = [
            linha.split("==")[0].strip()
            for linha in (RAIZ / "services/agr/requirements/runtime.txt").read_text(
                encoding="utf-8"
            ).splitlines()
            if "==" in linha and not linha.strip().startswith("#")
        ]
        self.assertGreater(len(declarados), 40, "o fecho nao se leu")
        from unittest import mock

        class Falsa:
            def __init__(self, nome: str) -> None:
                self.metadata = {"Name": nome}
                self.version = "1.0.0"

        with mock.patch(
            "kamba_agr.egresso.importlib.metadata.distributions",
            return_value=[Falsa(n) for n in declarados],
        ):
            exigir_sbom_mit()  # nao levanta: o fecho declarado esta limpo
        # E neste interpretador tambem, que e uma afirmacao mais fraca e vale
        # a pena ter: um `pip install` a mao aqui aparece.
        exigir_sbom_mit()

    def test_cada_entrada_da_lista_morde(self) -> None:
        for entrada in DISTRIBUICOES_PROIBIDAS:
            versao = "0.1.0" if entrada.limiar is None else "1.82.7"
            with self.subTest(pacote=entrada.nome), self._instalada(entrada.nome, versao):
                with self.assertRaises(ModuloProibidoError) as apanhado:
                    exigir_sbom_mit()
                self.assertIn(entrada.nome, str(apanhado.exception))

    def test_o_checkpointer_postgres_e_apanhado_aqui_e_nao_pela_outra_guarda(self) -> None:
        """O caso que justifica esta metade existir."""
        import importlib.util

        self.assertIsNotNone(
            importlib.util.find_spec("langgraph.checkpoint"),
            "o namespace `langgraph.checkpoint` e nosso e esta instalado",
        )
        exigir_biblioteca_mit()  # a outra guarda passa, e esta certa a passar
        with self._instalada("langgraph_checkpoint_postgres", "3.1.2"):
            with self.assertRaises(ModuloProibidoError):
                exigir_sbom_mit()

    def test_a_normalizacao_e_a_de_pep_503(self) -> None:
        for bruto in ("langgraph_api", "LangGraph-API", "langgraph..api", "LangGraph_-.API"):
            with self.subTest(nome=bruto):
                self.assertEqual(normalizar(bruto), "langgraph-api")
        with self._instalada("LangGraph_API", "0.1.0"):
            with self.assertRaises(ModuloProibidoError):
                exigir_sbom_mit()

    def test_a_fronteira_de_palavra_nao_apanha_quem_ninguem_escolheu(self) -> None:
        """A licao do ADR-L001 §10: um gate que bloqueia o que ninguem escolheu
        e um gate que alguem acaba por desligar."""
        # `n8n-ish-nope` esteve nesta lista e **nao** pertence aqui: o `n8n`
        # delimitado por `-` bate na fronteira, de propósito — e o que apanha o
        # `n8n-nodes-base`. O `lint_arch` decide o mesmo, e o teste de paridade
        # mede-o.
        for inocente in ("minion", "dominion", "modify-values", "codify", "typebotanical"):
            with self.subTest(pacote=inocente), self._instalada(inocente, "1.0.0"):
                exigir_sbom_mit()  # nao levanta
        for culpado in ("n8n-nodes-base", "dify-client", "minio", "langgenius-typebot"):
            with self.subTest(pacote=culpado), self._instalada(culpado, "1.0.0"):
                with self.assertRaises(ModuloProibidoError):
                    exigir_sbom_mit()

    def test_o_limiar_do_litellm_deixa_passar_o_que_esta_acima(self) -> None:
        """As versoes 1.82.7 e 1.82.8 foram publicadas com malware; o que esta
        proibido sao elas, nao o pacote (`E4` §2.7)."""
        for proibida in ("1.82.7", "1.82.8", "1.0.0", "0.9"):
            with self.subTest(versao=proibida), self._instalada("litellm", proibida):
                with self.assertRaises(ModuloProibidoError):
                    exigir_sbom_mit()
        for permitida in ("1.83.0", "1.104.2", "2.0.0"):
            with self.subTest(versao=permitida), self._instalada("litellm", permitida):
                exigir_sbom_mit()  # nao levanta

    def test_uma_versao_ilegivel_trata_se_como_abaixo_do_limiar(self) -> None:
        """«Nao provado» trata-se como «nao permitido» para um pacote que ja foi
        vector de ataque — a regra que o ADR-L001 §10 escreveu para as imagens
        fixadas por digest sem versao na tag."""
        for ilegivel in ("", "main", "1.83.0rc1", "v1.83.0"):
            with self.subTest(versao=ilegivel), self._instalada("litellm", ilegivel):
                with self.assertRaises(ModuloProibidoError):
                    exigir_sbom_mit()

    def test_metadados_ilegiveis_nao_derrubam_o_arranque(self) -> None:
        """A guarda recusa pacotes, nao interpretes."""
        from unittest import mock

        class Rebenta:
            @property
            def metadata(self):
                raise ValueError("metadados corrompidos")

        class SemNome:
            metadata: dict[str, str] = {}
            version = "1.0.0"

        with mock.patch(
            "kamba_agr.egresso.importlib.metadata.distributions",
            return_value=[Rebenta(), SemNome()],
        ):
            exigir_sbom_mit()  # nao levanta

    def _entradas_pypi_do_ficheiro(self):
        """As entradas de `tools/blocklist.yaml` que podem estar em Python.

        Le-se pelo `lint_arch.blocklist`, que e quem ja valida este ficheiro
        campo a campo — e **nao** se reimplementa aqui: «um ficheiro de bloqueio
        malformado nao pode degradar em silencio para uma lista vazia».
        """
        import sys as _sys

        _sys.path.insert(0, str(RAIZ / "tools"))
        try:
            from lint_arch.blocklist import load_entries

            return [
                entrada
                for entrada in load_entries(RAIZ / "tools/blocklist.yaml")
                if entrada.applies_to_kind("pypi")
            ]
        finally:
            _sys.path.remove(str(RAIZ / "tools"))

    def test_a_guarda_cobre_todas_as_entradas_pypi_da_lista_de_bloqueio(self) -> None:
        """A tabela do codigo **e** `tools/blocklist.yaml`, nos dois sentidos.

        Sem este teste a tabela era uma copia a envelhecer: uma entrada nova no
        ficheiro ficava sem guarda em *runtime*, e uma entrada retirada ficava a
        bloquear um pacote que o ADR ja permite.

        **Porque e que ha duas copias.** O `tools/` nao esta no `PYTHONPATH` do
        contentor do AGR (`libs/py-core/src` e `services/agr/src`, e o
        `Dockerfile` nao o copia), pelo que a guarda de *runtime* nao pode
        importar o `lint_arch`. O que a mantem honesta e este teste.

        As entradas `kind: npm` e `kind: image` ficam de fora **de proposito** —
        nao sao distribuicoes Python e nao se finge verifica-las aqui; quem as
        verifica e o `lint_arch` do *gate* 2, sobre os *lockfiles* e os
        `Dockerfile`.
        """
        do_ficheiro = {normalizar(e.name) for e in self._entradas_pypi_do_ficheiro()}
        self.assertEqual(
            sorted(do_ficheiro),
            sorted(e.nome for e in DISTRIBUICOES_PROIBIDAS),
            "a tabela de `egresso.py` divergiu de `tools/blocklist.yaml`",
        )

    def test_as_duas_implementacoes_decidem_o_mesmo(self) -> None:
        """Paridade de **comportamento**, com o `lint_arch` real dos dois lados.

        Comparar `match` e `forbidden_below` provaria que os dois ficheiros dizem
        o mesmo; isto prova que os dois **decidem** o mesmo.

        **A primeira versão reimplementava a comparação de versões aqui**, e a
        revisão adversarial mostrou que isso escondia duas divergências, uma em
        cada sentido: `1.83` (o lint permitia, a guarda bloqueava — o `compare`
        dele iguala as larguras) e `1.84.0.post1` (a guarda permitia, o lint
        bloqueava — não é um pin exacto, logo não está provado). A segunda era a
        grave: o controlo que protege o que **corre** era o mais frouxo dos dois.

        Agora chama-se o `versions.satisfies_floor` verdadeiro, e a amostra leva
        as duas versões que divergiam.
        """
        import sys as _sys

        _sys.path.insert(0, str(RAIZ / "tools"))
        try:
            from lint_arch import versions
        finally:
            _sys.path.remove(str(RAIZ / "tools"))

        entradas = self._entradas_pypi_do_ficheiro()
        candidatos = [
            "langgraph", "langgraph-api", "langgraph_api", "langgraph-checkpoint",
            "langgraph-checkpoint-postgres", "langgraph-runtime-inmem", "psycopg",
            "psycopg-pool", "psycopg2-binary", "psycopg2", "pydantic", "dify",
            "dify-client", "n8n", "n8n-nodes-base", "typebot", "minio", "minion",
            "dominion", "modify-values", "codify", "nodify", "litellm", "pg8000",
            "starlette",
        ]
        versoes = [
            "1.0.0", "1.82.7", "1.82.8", "1.83", "1.83.0", "1.84.0.post1",
            "1.104.2", "2.0.0", "0.9", "", "main", "1.83.0rc1",
        ]
        for nome in candidatos:
            for versao in versoes:
                with self.subTest(pacote=nome, versao=versao):
                    do_lint = any(
                        entrada.matches_name(nome, "pypi")
                        and (
                            entrada.forbidden_below is None
                            or not versions.satisfies_floor(versao, entrada.forbidden_below)[0]
                        )
                        for entrada in entradas
                    )
                    with self._instalada(nome, versao):
                        try:
                            exigir_sbom_mit()
                            da_guarda = False
                        except ModuloProibidoError:
                            da_guarda = True
                    self.assertEqual(
                        da_guarda,
                        do_lint,
                        f"`{nome}` {versao!r}: a guarda de runtime diz {da_guarda} e o "
                        f"`lint_arch` diz {do_lint}",
                    )

    def test_as_duas_divergencias_que_a_revisao_encontrou(self) -> None:
        """Nomeadas, para que uma regressão as volte a apanhar pelo nome."""
        import sys as _sys

        _sys.path.insert(0, str(RAIZ / "tools"))
        try:
            from lint_arch import versions
        finally:
            _sys.path.remove(str(RAIZ / "tools"))

        # `1.83` e a mesma versao que `1.83.0`: as duas permitem.
        self.assertTrue(versions.satisfies_floor("1.83", "1.83.0")[0])
        with self._instalada("litellm", "1.83"):
            exigir_sbom_mit()  # nao levanta
        # `1.84.0.post1` nao e um pin exacto: as duas bloqueiam.
        self.assertFalse(versions.satisfies_floor("1.84.0.post1", "1.83.0")[0])
        with self._instalada("litellm", "1.84.0.post1"):
            with self.assertRaises(ModuloProibidoError):
                exigir_sbom_mit()


class TestTelemetria(unittest.TestCase):
    def test_poe_as_duas_variaveis_a_false(self) -> None:
        ambiente: dict[str, str] = {}
        desligar_telemetria(ambiente)
        for variavel in VARIAVEIS_DE_TELEMETRIA:
            self.assertEqual(ambiente[variavel], TELEMETRIA_DESLIGADA)

    def test_sobrepoe_um_true_do_ambiente(self) -> None:
        # Criterio 7. Um AGR que respeitasse um `LANGSMITH_TRACING=true` mandava
        # conteudo de conversas de clientes para fora de Angola sem destino
        # registado (ADR-008).
        ambiente = {v: "true" for v in VARIAVEIS_DE_TELEMETRIA}
        mudou = desligar_telemetria(ambiente)
        for variavel in VARIAVEIS_DE_TELEMETRIA:
            self.assertEqual(ambiente[variavel], TELEMETRIA_DESLIGADA)
        self.assertEqual(sorted(mudou), sorted(VARIAVEIS_DE_TELEMETRIA))

    def test_o_que_devolve_nao_leva_o_valor_que_la_estava(self) -> None:
        """Um `LANGSMITH_TRACING` pode trazer uma chave colada por engano.

        **E a primeira versao deste teste nao podia falhar.** A funcao devolvia
        `{nome: valor_anterior}` e a asercao era `assertNotIn("segredo",
        " ".join(mudou))` — `" ".join(dict)` itera as **chaves**, pelo que o
        valor nunca era olhado. Hoje a funcao devolve um `tuple` de nomes, que
        nao pode levar o valor, e a asercao percorre o que ha. Achado da
        revisao adversarial.
        """
        segredo = "lsv2_pt_923456789_colado_por_engano"
        ambiente = {"LANGSMITH_TRACING": segredo}
        mudou = desligar_telemetria(ambiente)
        self.assertIsInstance(mudou, tuple)
        # As duas mudaram: a que trazia o valor, e a que nao estava definida.
        self.assertEqual(sorted(mudou), sorted(VARIAVEIS_DE_TELEMETRIA))
        for item in mudou:
            self.assertIn(item, VARIAVEIS_DE_TELEMETRIA)
            self.assertNotIn(segredo, item)
        self.assertNotIn(segredo, " ".join(mudou))
        self.assertNotIn(segredo, repr(mudou))

    def test_com_as_duas_ja_a_false_nao_declara_mudanca(self) -> None:
        ambiente = {v: TELEMETRIA_DESLIGADA for v in VARIAVEIS_DE_TELEMETRIA}
        self.assertEqual(desligar_telemetria(ambiente), ())


class TestAllowlistDeSaida(unittest.TestCase):
    """O contrato de `egress.yaml`: e nele que «0 chamadas ao beacon» vive hoje."""

    def setUp(self) -> None:
        self.texto = (RAIZ / "services" / "agr" / "egress.yaml").read_text(
            encoding="utf-8"
        )

    def test_o_beacon_nao_esta_na_allowlist(self) -> None:
        self.assertNotIn(BEACON, _destinos(self.texto))
        # E **esta** no ficheiro: num comentario que diz porque e que nao esta
        # na lista. Apagar o comentario nao melhora nada, e este teste nota-o.
        self.assertIn(BEACON, self.texto)

    def test_a_omissao_continua_a_ser_negar(self) -> None:
        self.assertIn("por_omissao: negar", self.texto)

    def test_nenhum_destino_e_um_caracter_universal(self) -> None:
        for proibido in ("fqdn: '*'", 'fqdn: "*"', "fqdn: *"):
            self.assertNotIn(proibido, self.texto)


def _destinos(texto: str) -> str:
    """A parte do ficheiro depois de `destinos:`, sem os comentarios.

    O `beacon.langchain.com` **esta** no ficheiro, num comentario que explica
    porque e que nao esta na lista. Procurar a cadeia no ficheiro inteiro fazia
    este teste falhar pela razao errada — ou, pior, passar por o comentario ter
    sido apagado.
    """
    _, _, cauda = texto.partition("destinos:")
    return "\n".join(
        linha for linha in cauda.splitlines() if not linha.strip().startswith("#")
    )


if __name__ == "__main__":
    unittest.main()
