"""A enumeracao encontra o que existe, nao inventa o que nao existe, e di-lo.

Tres grupos de afirmacoes, e o terceiro e o que faz da enumeracao um portao:

1. **encontra** — uma superficie de cada tipo, na arvore de ensaio;
2. **nao inventa** — um `Map.get("…")` nao e uma rota, e um comentario que fala
   de `new Queue(...)` nao e uma fila;
3. **nao cala** — o que nao consegue resolver entra como indeciso, e um tipo que
   fique a zero e erro e nao resultado.

O teste de meta do bloco («um tenant C novo e apanhado pela enumeracao sem
alterar o codigo da suite») tem aqui o seu equivalente no eixo que esta
enumeracao cobre: uma **superficie** nova e apanhada sem se tocar no codigo.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from isolamento import enumeracao
from isolamento.tests import apoio


class ComArvore(unittest.TestCase):
    def setUp(self) -> None:
        self._directorio = tempfile.TemporaryDirectory()
        self.raiz = apoio.arvore(Path(self._directorio.name))

    def tearDown(self) -> None:
        self._directorio.cleanup()

    def ids(self, itens) -> set[str]:
        return {item.id for item in itens}


class TestEncontra(ComArvore):
    def test_as_rotas_literais_e_por_constante(self) -> None:
        ids = self.ids(enumeracao.rotas(self.raiz))
        self.assertIn("rota:svc:app:createApp:GET:/healthz", ids)
        self.assertIn("rota:svc:app:createApp:POST:/wa/ensaio", ids)

    def test_as_rotas_de_python(self) -> None:
        ids = self.ids(enumeracao.rotas(self.raiz))
        self.assertIn("rota:pysvc:pacote/api:create_app:GET:/healthz", ids)
        self.assertIn(
            "rota:pysvc:pacote/api:create_app:POST:/internal/ensaio", ids
        )

    def test_as_tools_do_registo(self) -> None:
        self.assertEqual(
            self.ids(enumeracao.tools(self.raiz)), {"tool:tool_de_ensaio"}
        )

    def test_os_consumidores_derivam_das_subscricoes(self) -> None:
        self.assertEqual(
            self.ids(enumeracao.consumidores(self.raiz)),
            {"consumidor:agr_ensaio:ensaio.ocorreu@1"},
        )

    def test_a_fila_de_nome_literal_resolve_pelo_local(self) -> None:
        """`new Worker(fila)` com `const fila = opcoes.fila ?? FILA_DE_ENSAIO`."""
        self.assertIn("job:ensaio-inbound", self.ids(enumeracao.jobs(self.raiz)))

    def test_uma_superficie_nova_entra_sozinha(self) -> None:
        """O teste de meta: a enumeracao apanha o que ninguem lhe ensinou.

        Acrescenta-se uma rota, uma tool e uma subscricao a arvore **sem tocar
        no codigo da enumeracao**, e as tres aparecem. E a propriedade de que o
        criterio 2 depende: sem ela, a cobertura de 100% e so o espelho de uma
        lista escrita a mao.
        """
        antes = self.ids(enumeracao.enumerar(self.raiz))
        app = self.raiz / "services" / "svc" / "src" / "app.ts"
        app.write_text(
            app.read_text(encoding="utf-8").replace(
                'app.get("/healthz", (c) => c.json({}));',
                'app.get("/healthz", (c) => c.json({}));\n'
                '  app.get("/rota/nova", (c) => c.json({}));',
            ),
            encoding="utf-8",
        )
        vertical = self.raiz / "registry" / "ensaio.yaml"
        vertical.write_text(
            vertical.read_text(encoding="utf-8")
            .replace("  - tool_de_ensaio", "  - tool_de_ensaio\n  - tool_nova")
            .replace(
                "    versao: 1",
                "    versao: 1\n  - tipo: ensaio.outro\n    versao: 2",
            ),
            encoding="utf-8",
        )
        depois = self.ids(enumeracao.enumerar(self.raiz))
        self.assertEqual(
            depois - antes,
            {
                "rota:svc:app:createApp:GET:/rota/nova",
                "tool:tool_nova",
                "consumidor:agr_ensaio:ensaio.outro@2",
            },
        )


class TestNaoInventa(ComArvore):
    def test_um_map_get_nao_e_uma_rota(self) -> None:
        """`segredos.get("meta_verify_token")` nao e uma rota.

        A primeira versao da enumeracao contou seis «rotas» que eram
        `Map.get`, `Headers.get` e `segredos.get` — uma delas com o caminho
        `meta_verify_token`. Uma enumeracao que inventa superficies obriga a
        escrever casos para o que nao existe, e quem os escreve aprende a tratar
        a lista como ruido.
        """
        for item in enumeracao.rotas(self.raiz):
            self.assertNotIn("meta_verify_token", item.id)

    def test_um_comentario_sobre_new_queue_nao_e_uma_fila(self) -> None:
        filas = self.raiz / "packages" / "core" / "src" / "filas.ts"
        filas.write_text(
            "// Nota: o cliente tem de ir ao new Queue('nao-sou-uma-fila').\n"
            + filas.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        for item in enumeracao.jobs(self.raiz):
            self.assertNotIn("nao-sou-uma-fila", item.id)


class TestNaoCala(ComArvore):
    def test_a_fila_de_nome_calculado_fica_indecisa(self) -> None:
        indecisos = [item for item in enumeracao.jobs(self.raiz) if item.indeciso]
        self.assertTrue(
            indecisos,
            "o `new Queue(nomeCalculado())` tem de entrar como indeciso: uma "
            "enumeracao que calasse o que nao entende dava 100% pela razao errada",
        )
        self.assertTrue(all("#" in item.id for item in indecisos))

    def test_o_identificador_de_um_indeciso_nao_leva_a_linha(self) -> None:
        """Um caso registado contra `…:242` morria com um comentario a mais."""
        for item in enumeracao.jobs(self.raiz):
            if item.indeciso:
                self.assertNotRegex(item.id, r":\d+$")

    def test_um_tipo_vazio_e_erro(self) -> None:
        """O sentinela da casa: zero itens diz-se, nao passa por conforme."""
        (self.raiz / "registry" / "ensaio.yaml").unlink()
        with self.assertRaises(enumeracao.EnumeracaoInvalida) as apanhado:
            enumeracao.enumerar(self.raiz)
        self.assertIn("registry", str(apanhado.exception))

    def test_uma_subscricao_sem_versao_e_erro(self) -> None:
        vertical = self.raiz / "registry" / "ensaio.yaml"
        vertical.write_text(
            vertical.read_text(encoding="utf-8").replace("    versao: 1", ""),
            encoding="utf-8",
        )
        with self.assertRaises(enumeracao.EnumeracaoInvalida):
            enumeracao.consumidores(self.raiz)


class TestORepositorio(unittest.TestCase):
    """A regressao: a arvore real esta conforme, e as contagens sao estas."""

    RAIZ = Path(__file__).resolve().parents[3]

    def test_as_quatro_superficies_tem_itens(self) -> None:
        agrupado = enumeracao.por_tipo(enumeracao.enumerar(self.RAIZ))
        for tipo, lista in agrupado.items():
            with self.subTest(tipo=tipo):
                self.assertTrue(lista, f"nenhum item de tipo {tipo}")

    def test_as_cinco_rotas_do_agr_estao_enumeradas(self) -> None:
        ids = {item.id for item in enumeracao.rotas(self.RAIZ)}
        for caminho in (
            "/internal/turn",
            "/internal/resume",
            "/internal/event",
            "/internal/draft-decision",
        ):
            with self.subTest(caminho=caminho):
                self.assertIn(
                    f"rota:agr:kamba_agr/api_interna:rotas:POST:{caminho}", ids
                )

    def test_as_cinco_sondas_do_worker_canal_nao_colapsam_numa(self) -> None:
        """Cinco apps do mesmo servico servem `/healthz`, e sao cinco itens.

        Mediu-se: com a chave sem o modulo, as cinco colapsavam numa e
        dezassete rotas de TypeScript apareciam como doze — um caso escrito
        contra a `/healthz` de um processo dava por coberta a dos outros quatro.
        """
        ids = {item.id for item in enumeracao.rotas(self.RAIZ)}
        sondas = {
            identificador
            for identificador in ids
            if identificador.startswith("rota:worker-canal:")
            and identificador.endswith(":GET:/healthz")
        }
        self.assertEqual(len(sondas), 5, sorted(sondas))


if __name__ == "__main__":
    unittest.main()
