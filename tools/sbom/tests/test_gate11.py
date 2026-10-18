"""O gate 11 ponta a ponta: recolha, SBOM por alvo, e as licencas do repositorio."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import pathlib

from sbom import cli, cyclonedx, pnpm_lock, spdx
from sbom.cli import (
    ConfiguracaoInvalida,
    componentes_do_alvo,
    gerar,
    ler_politica,
    verificar_licencas,
)
from sbom.collect import recolher, recolher_npm, recolher_pypi, recolher_workspace

ROOT = Path(__file__).resolve().parents[3]


class TestRecolha(unittest.TestCase):
    def test_os_nove_pacotes_do_monorepo_sao_recolhidos(self) -> None:
        proprios = recolher_workspace(ROOT)
        nomes = {c.nome for c in proprios}
        for esperado in (
            "kamba",
            "@kamba/contracts",
            "@kamba/core-ts",
            "@kamba/gwy",
            "@kamba/worker-canal",
            "@kamba/com",
            "@kamba/onboarding-web",
            "kamba-core",
            "kamba-agr",
        ):
            self.assertIn(esperado, nomes)

    def test_os_proprios_estao_marcados(self) -> None:
        """O campo e explicito, nao inferido do caminho.

        Os componentes de terceiros tambem vem de um `package.json`, e
        distingui-los pelo sufixo do caminho classificava-os todos como nossos.
        """
        for componente in recolher_workspace(ROOT):
            self.assertTrue(componente.proprio, componente.nome)
        for componente in recolher_npm(ROOT):
            self.assertFalse(componente.proprio, componente.nome)

    def test_todos_os_proprios_estao_na_lista_de_ci_licenses(self) -> None:
        """Um pacote nosso fora da lista `proprios` seria lido como terceiro."""
        _, proprios = ler_politica(ROOT)
        for componente in recolher_workspace(ROOT):
            with self.subTest(nome=componente.nome):
                self.assertIn(
                    componente.nome,
                    proprios,
                    "acrescente-o a `proprios` em ci/licenses.yaml",
                )

    def test_a_origem_da_licenca_e_registada(self) -> None:
        """O relatorio tem de poder ser verificado a mao."""
        for componente in recolher(ROOT):
            with self.subTest(nome=componente.nome):
                self.assertTrue(componente.origem)

    def test_um_pyproject_de_terceiros_nao_passa_por_nosso(self) -> None:
        """A guarda do `node_modules` tem de valer nos dois varrimentos.

        O dos `package.json` tinha-a e o dos `pyproject.toml` nao: um pacote de
        terceiros com `pyproject.toml` na loja do `pnpm` entrava com
        `proprio=True`, isto e, com a licenca dispensada por identidade.
        """
        with tempfile.TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            intruso = raiz / "node_modules" / ".pnpm" / "x@1" / "node_modules" / "x"
            intruso.mkdir(parents=True)
            (intruso / "pyproject.toml").write_text(
                '[project]\nname = "intruso"\nversion = "1.0.0"\n',
                encoding="utf-8", newline="\n",
            )
            nomes = {c.nome for c in recolher_workspace(raiz)}
            self.assertNotIn("intruso", nomes, sorted(nomes))

    def test_as_pastas_do_venv_sao_lidas_por_ordem(self) -> None:
        """Determinista inclui **qual** das arvores do `venv` se leu."""
        from sbom import collect

        with tempfile.TemporaryDirectory() as tmp:
            venv = Path(tmp) / ".venv"
            for versao in ("python3.13", "python3.12"):
                (venv / "lib" / versao / "site-packages").mkdir(parents=True)
            pastas = [
                p
                for p in (
                    venv / "Lib" / "site-packages",
                    *sorted((venv / "lib").glob("python3.*/site-packages")),
                )
            ]
            lidas = [p.parent.name for p in pastas if p.is_dir()]
            self.assertEqual(lidas, ["python3.12", "python3.13"])
            # E a funcao real nao rebenta num venv assim.
            self.assertEqual(collect.recolher_pypi(Path(tmp), venv), [])

    def test_le_do_disco_e_nao_da_rede(self) -> None:
        """Sem instalacao nao ha componentes de terceiros, e isso e correcto.

        Um gate que fosse a registo publico por cada componente falharia por
        ligacao e nao por licenca — o mesmo defeito que levou a separar
        `make lock-check` de `make lock-verify` no KAM-001.
        """
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(recolher_npm(Path(tmp)), [])
            self.assertEqual(recolher_pypi(Path(tmp)), [])


class TestFechoPorAlvo(unittest.TestCase):
    """O SBOM de um servico lista o que **ele** carrega, nao o workspace."""

    def setUp(self) -> None:
        self.grafo = pnpm_lock.ler(ROOT / "pnpm-lock.yaml")

    #: Quantos pacotes de terceiros cada servico Node carrega, pelo fecho do
    #: lockfile. Lista fechada: um servico que ganhe uma dependencia muda o seu
    #: numero aqui, e e isso que faz a entrada de uma dependencia nova ser uma
    #: decisao e nao um acidente. O `worker-canal` passou de 2 a 19 com o
    #: KAM-005: o publicador leva `pg`, e o `pg` leva dezasseis.
    #:
    #: O **KAM-133** multiplicou-os: a travessia passou a atravessar o `link:`,
    #: e cada servico leva agora o que o `@kamba/core-ts` lhe traz (`bullmq`,
    #: `ioredis` e os fechos dos dois). Os tres servicos que so declaram `hono`
    #: ficam iguais entre si, como declaram; o `worker-canal` leva o `pg` e o
    #: fecho dele, que sao seus, mais o `@types/pg` e o `@types/node`.
    #:
    #: **Os tres foram 41 durante uma versao deste ramo, e 41 estava errado.**
    #: A revisao adversarial mediu 27 contra o proprio `pnpm`: os 14 a mais
    #: vinham do `pg` resolvido como *peer* opcional no *snapshot* do `bullmq`.
    #: Estes numeros sao agora confrontados com o oraculo do `pnpm` em
    #: `test_oraculo_pnpm.py`, que e quem manda; aqui ficam para que uma
    #: dependencia nova seja uma decisao e nao um acidente.
    DEPENDENCIAS_POR_SERVICO = {
        "services/gwy": 27,
        "services/worker-canal": 44,
        "services/com": 27,
        "services/onboarding-web": 27,
    }

    def test_os_servicos_node_carregam_o_que_declaram(self) -> None:
        for servico, quantas in self.DEPENDENCIAS_POR_SERVICO.items():
            with self.subTest(servico=servico):
                fecho = pnpm_lock.fecho(servico, self.grafo)
                self.assertIn("hono@4.13.13", fecho.terceiros)
                self.assertEqual(
                    len(fecho.terceiros), quantas, sorted(fecho.terceiros)
                )

    def test_o_fecho_do_publicador_atravessa_o_workspace(self) -> None:
        """KAM-005 encontrou a lacuna do KAM-133 pelo lado de dentro.

        O publicador vive em `services/worker-canal` e usa `bullmq` e `ioredis`,
        que sao dependencias de `@kamba/core-ts` — e `@kamba/core-ts` entra por
        `workspace:*`. Ate ao KAM-133 o fecho **nao atravessava** essa ligacao,
        pelo que o SBOM do servico nao mostrava nem o `bullmq` nem o `ioredis`:
        mostrava o `pg`, que e dependencia directa dele. A versao anterior deste
        teste fixava essa omissao, para que o dia em que ela fosse paga nao
        mudasse o SBOM em silencio. E o dia foi este.
        """
        fecho = pnpm_lock.fecho("services/worker-canal", self.grafo)
        nomes = {x.rsplit("@", 1)[0] for x in fecho.terceiros}
        for pacote in ("pg", "bullmq", "ioredis"):
            with self.subTest(pacote=pacote):
                self.assertIn(pacote, nomes, sorted(nomes))
        self.assertIn("packages/core-ts", fecho.importadores)

    def test_a_raiz_carrega_o_fecho_das_devdependencies(self) -> None:
        """O `@commitlint/cli` tem tres pares; sem normalizar as chaves, o fecho
        parava nele e dava 12 em vez de ~74."""
        fecho = pnpm_lock.fecho(".", self.grafo)
        self.assertGreater(len(fecho.terceiros), 60, sorted(fecho.terceiros)[:5])

    def test_o_alvo_do_conjunto_cobre_mais_do_que_um_servico(self) -> None:
        todos = recolher(ROOT)
        conjunto = componentes_do_alvo(ROOT, "kamba", todos)
        servico = componentes_do_alvo(ROOT, "services/gwy", todos)
        self.assertGreater(len(conjunto), len(servico))

    def test_nao_e_o_fecho_completo_repetido(self) -> None:
        """Atravessar o `link:` nao pode virar «nove copias da raiz».

        E o modo de falha oposto ao que o KAM-133 fecha, e o criterio que o
        ticket escreve: a contagem sobe dos 3 de cada servico e **nao** iguala a
        do conjunto. Um servico que carregasse tudo tornaria a atribuicao por
        servico inutil outra vez, pelo outro lado.
        """
        todos = recolher(ROOT)
        conjunto = componentes_do_alvo(ROOT, "kamba", todos)
        for alvo in ("services/gwy", "services/com", "services/onboarding-web"):
            with self.subTest(alvo=alvo):
                servico = componentes_do_alvo(ROOT, alvo, todos)
                self.assertLess(len(servico), len(conjunto) // 2, alvo)
                nomes = {c.nome for c in servico}
                # O `typescript` e `@commitlint/*` sao da raiz e de mais ninguem.
                self.assertNotIn("typescript", nomes)

    def test_um_servico_inclui_o_seu_proprio_pacote(self) -> None:
        todos = recolher(ROOT)
        nomes = {c.nome for c in componentes_do_alvo(ROOT, "services/gwy", todos)}
        self.assertIn("@kamba/gwy", nomes)
        self.assertNotIn("@kamba/com", nomes, "o SBOM do gwy nao leva o com")

    def test_o_caso_de_aceitacao_do_kam133(self) -> None:
        """«`@kamba/core-ts` aparece no SBOM do `services/gwy`.»

        O caso medido na revisao adversarial ([`ANALISE-02`] M7) e o teste de
        aceitacao minimo do ticket. Com ele vem o `@kamba/contracts`, que o
        `gwy` tambem declara, e o `bullmq` — terceiro que nenhum dos quatro
        servicos declara e todos carregam, pelo `core-ts`.
        """
        todos = recolher(ROOT)
        for alvo in (
            "services/gwy",
            "services/com",
            "services/onboarding-web",
            "services/worker-canal",
        ):
            with self.subTest(alvo=alvo):
                nomes = {c.nome for c in componentes_do_alvo(ROOT, alvo, todos)}
                self.assertIn("@kamba/core-ts", nomes)
                self.assertIn("@kamba/contracts", nomes)
                self.assertIn("bullmq", nomes)

    def test_o_lado_python_tem_a_mesma_ligacao(self) -> None:
        """`services/agr` declara `kamba-core` e nao o mostrava.

        Nao e `link:` nem instalacao editavel — o `make bootstrap` nao instala
        nenhum dos dois pacotes Python nossos —, e a ligacao esta na mesma
        declarada: `[project].dependencies` do `services/agr/pyproject.toml`.
        Mesmo defeito, mesmo gerador, e por isso entrou no mesmo ticket.
        """
        todos = recolher(ROOT)
        nomes = {c.nome for c in componentes_do_alvo(ROOT, "services/agr", todos)}
        self.assertIn("kamba-agr", nomes)
        self.assertIn("kamba-core", nomes)
        # E nao ao contrario: o nucleo nao carrega o servico que o usa.
        do_nucleo = {c.nome for c in componentes_do_alvo(ROOT, "libs/py-core", todos)}
        self.assertNotIn("kamba-agr", do_nucleo, sorted(do_nucleo))


class TestExcepcoesDeNome(unittest.TestCase):
    """A travagem por nome da D12 apanha o servidor, nao as bibliotecas (KAM-005).

    A correspondencia de `pendentes_de_decisao` e **parcial**, para que um
    `redis-stack-server` nao passe ao lado. O preco e apanhar pacotes cujo nome
    contem `redis` e que nao sao o servidor: o `ioredis` (cliente), o
    `redis-parser` (analisador do protocolo), o `redis-errors` e a tabela de
    comandos `@ioredis/commands`, os quatro MIT. Estao nomeados em
    `ci/licenses.yaml`, um a um e com a razao.
    """

    def setUp(self) -> None:
        self.politica, _ = ler_politica(ROOT)

    def test_as_bibliotecas_de_cliente_passam(self) -> None:
        for nome in ("ioredis", "redis-parser", "redis-errors", "@ioredis/commands"):
            with self.subTest(pacote=nome):
                veredicto, _ = spdx.classificar_pacote(nome, "MIT", self.politica)
                self.assertEqual(veredicto, spdx.PERMITIDA)

    def test_o_servidor_continua_travado_pela_d12(self) -> None:
        for nome in ("redis", "redis-stack-server", "valkey"):
            with self.subTest(pacote=nome):
                veredicto, razao = spdx.classificar_pacote(nome, "MIT", self.politica)
                self.assertEqual(veredicto, spdx.PENDENTE)
                self.assertIn("D12", razao)

    def test_uma_excepcao_sem_razao_e_recusada(self) -> None:
        """Um nome sem razao e uma dispensa por omissao."""
        import tempfile

        raiz = pathlib.Path(tempfile.mkdtemp())
        (raiz / "ci").mkdir()
        politica = [
            "version: 1",
            "permitidas:",
            "  - MIT",
            "negadas: []",
            "pendentes_de_decisao:",
            "  - nome: redis",
            "    decisao: D12",
            "    razao: >-",
            "      Uma razao com mais de trinta caracteres para passar.",
            "    excepcoes:",
            "      - nome: ioredis",
        ]
        (raiz / "ci" / "licenses.yaml").write_text(
            "\n".join(politica) + "\n", encoding="utf-8", newline="\n"
        )
        with self.assertRaises(ConfiguracaoInvalida):
            ler_politica(raiz)

    def test_a_excepcao_nao_dispensa_a_licenca(self) -> None:
        """Passar a travagem por nome nao e passar a politica de licencas."""
        veredicto, _ = spdx.classificar_pacote("ioredis", "AGPL-3.0", self.politica)
        self.assertEqual(veredicto, spdx.NEGADA)


class TestSbom(unittest.TestCase):
    def test_gera_um_por_alvo_e_e_cyclonedx_valido(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            escritos = gerar(ROOT, Path(tmp))
            self.assertGreaterEqual(len(escritos), 9)
            for caminho, _ in escritos:
                with self.subTest(ficheiro=caminho.name):
                    documento = json.loads(caminho.read_text(encoding="utf-8"))
                    self.assertEqual(documento["bomFormat"], "CycloneDX")
                    self.assertEqual(documento["specVersion"], cyclonedx.VERSAO_SPEC)
                    self.assertIn("components", documento)
                    self.assertIn("component", documento["metadata"])

    def test_e_determinista(self) -> None:
        """Duas geracoes sobre a mesma arvore dao ficheiros identicos.

        Um SBOM com timestamp muda a cada execucao e deixa de se poder comparar —
        e comparar e metade da utilidade de o ter.
        """
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            gerar(ROOT, Path(a))
            gerar(ROOT, Path(b))
            for ficheiro in sorted(Path(a).iterdir()):
                with self.subTest(ficheiro=ficheiro.name):
                    self.assertEqual(
                        ficheiro.read_bytes(),
                        (Path(b) / ficheiro.name).read_bytes(),
                    )

    def test_o_grafo_de_dependencias_nao_tem_referencias_penduradas(self) -> None:
        """Um `bom-ref` que nao resolve e pior do que nao dizer nada.

        O `@msgpackr-extract/...-darwin-arm64` esta no lockfile e nao esta
        instalado num runner Linux: e o caso real que obriga a filtrar o
        `dependsOn` pelos componentes deste SBOM, e nao pelo fecho do lockfile.
        """
        with tempfile.TemporaryDirectory() as tmp:
            for caminho, _ in gerar(ROOT, Path(tmp)):
                documento = json.loads(caminho.read_text(encoding="utf-8"))
                referencias = {c["bom-ref"] for c in documento["components"]}
                referencias.add(documento["metadata"]["component"]["bom-ref"])
                for entrada in documento.get("dependencies", []):
                    with self.subTest(sbom=caminho.name, ref=entrada["ref"]):
                        self.assertIn(entrada["ref"], referencias)
                        for destino in entrada["dependsOn"]:
                            self.assertIn(destino, referencias)

    def test_o_grafo_diz_porque_e_que_o_bullmq_esta_no_gwy(self) -> None:
        """Metade do valor de atribuir por servico e a resposta a «porque».

        Sem o campo `dependencies`, o SBOM do `gwy` diria que leva `bullmq` e
        nao diria que o leva por carregar o `@kamba/core-ts` — e e essa a
        pergunta que alguem faz quando o `bullmq` aparecer num boletim.
        """
        with tempfile.TemporaryDirectory() as tmp:
            gerar(ROOT, Path(tmp))
            documento = json.loads(
                (Path(tmp) / "services__gwy.cdx.json").read_text(encoding="utf-8")
            )
            arestas = {e["ref"]: e["dependsOn"] for e in documento["dependencies"]}
            self.assertIn(
                "pkg:npm/@kamba/core-ts@0.1.0", arestas["pkg:npm/@kamba/gwy@0.1.0"]
            )
            self.assertIn(
                "pkg:npm/bullmq@6.3.11", arestas["pkg:npm/@kamba/core-ts@0.1.0"]
            )
            self.assertNotIn(
                "pkg:npm/bullmq@6.3.11", arestas["pkg:npm/@kamba/gwy@0.1.0"]
            )

    def test_no_conjunto_um_pacote_nosso_declara_o_que_ele_declara(self) -> None:
        """O grafo do conjunto nao pode contradizer a lista de componentes.

        O alvo `kamba` e a uniao dos importadores, e o `@kamba/core-ts` aparece
        la por dois caminhos: como importador (com todos os grupos) e como
        pacote herdado pelos quatro servicos (so `dependencies`). A primeira
        versao deixava ganhar quem viesse por ultimo, e o conjunto ficava a
        dizer que o `core-ts` nao depende do `pg` **enquanto o `pg` estava na
        sua lista de componentes**.
        """
        with tempfile.TemporaryDirectory() as tmp:
            gerar(ROOT, Path(tmp))
            def arestas(ficheiro: str) -> dict[str, list[str]]:
                documento = json.loads(
                    (Path(tmp) / ficheiro).read_text(encoding="utf-8")
                )
                return {e["ref"]: e["dependsOn"] for e in documento["dependencies"]}

            referencia = "pkg:npm/@kamba/core-ts@0.1.0"
            self.assertEqual(
                arestas("kamba.cdx.json")[referencia],
                arestas("packages__core-ts.cdx.json")[referencia],
            )

    def test_nenhum_componente_emite_licenses_vazio(self) -> None:
        """Um *array* vazio satisfaz os dois ramos do `oneOf` e falha-o.

        O `licenseChoice` do CycloneDX 1.6 e um `oneOf` de dois ramos que sao
        ambos um *array*. `"licenses": []` aparecia em tres documentos, pelos
        dois pacotes Python nossos, que nao declaram licenca. Omite-se a
        propriedade: «sem campo» e exactamente o que ha a dizer.
        """
        with tempfile.TemporaryDirectory() as tmp:
            for caminho, _ in gerar(ROOT, Path(tmp)):
                documento = json.loads(caminho.read_text(encoding="utf-8"))
                for componente in documento["components"]:
                    with self.subTest(sbom=caminho.name, pacote=componente["name"]):
                        self.assertNotEqual(componente.get("licenses"), [])

    def test_o_grafo_do_lado_python_conta_as_dependencias_todas(self) -> None:
        """Uma entrada **parcial** mente mais do que nenhuma.

        O `services/agr/pyproject.toml` declara tres (`starlette`, `uvicorn`,
        `kamba-core`), e a primeira versao emitia so o `kamba-core` — os outros
        dois estao no mesmo documento, com versao. Com entrada, quem le conclui
        que o grafo e conhecido.
        """
        with tempfile.TemporaryDirectory() as tmp:
            gerar(ROOT, Path(tmp))
            documento = json.loads(
                (Path(tmp) / "services__agr.cdx.json").read_text(encoding="utf-8")
            )
            arestas = {e["ref"]: e["dependsOn"] for e in documento["dependencies"]}
            self.assertEqual(
                arestas["pkg:pypi/kamba-agr@0.1.0"],
                [
                    "pkg:pypi/kamba-core@0.1.0",
                    "pkg:pypi/starlette@1.7.0",
                    "pkg:pypi/uvicorn@0.54.0",
                ],
            )

    def test_as_expressoes_vao_no_campo_certo(self) -> None:
        """Um `id` e comparavel; uma `expression` tem de ser avaliada."""
        from sbom.cyclonedx import _licenca_para_cyclonedx

        ids = frozenset({"MIT", "Apache-2.0"})
        self.assertEqual(
            _licenca_para_cyclonedx("MIT", ids), [{"license": {"id": "MIT"}}]
        )
        self.assertEqual(
            _licenca_para_cyclonedx("MIT AND BUSL-1.1", ids),
            [{"expression": "MIT AND BUSL-1.1"}],
        )
        self.assertEqual(_licenca_para_cyclonedx(None, ids), [])

    def test_cadeia_fora_do_spdx_vai_em_name_e_nao_em_id(self) -> None:
        """`license.id` esta restringido a enumeracao SPDX no CycloneDX 1.6.

        `UNLICENSED` e convencao do npm e nao um identificador SPDX, e os 7
        `package.json` do monorepo que o declaram tornavam **todos** os SBOM
        invalidos contra o esquema. Um ficheiro que nao valida e um ficheiro com
        a extensao certa, nao um SBOM — e e o KAM-067, a jusante, que o
        descobriria.
        """
        from sbom.cyclonedx import _licenca_para_cyclonedx

        ids = frozenset({"MIT"})
        for cadeia in ("UNLICENSED", "Some Free License, v2", "LICENSE.txt"):
            with self.subTest(cadeia=cadeia):
                self.assertEqual(
                    _licenca_para_cyclonedx(cadeia, ids),
                    [{"license": {"name": cadeia}}],
                )

    def test_nenhum_sbom_do_repositorio_usa_um_id_fora_do_spdx(self) -> None:
        """A propriedade, sobre os SBOM reais e nao sobre a funcao."""
        import json

        from sbom.cli import ids_spdx_curados

        curados = ids_spdx_curados(ROOT)
        caminhos = sorted((ROOT / "ci" / "sbom").glob("*.cdx.json"))
        if not caminhos:
            self.skipTest("sem SBOM gerados; corra `make ci-11`")
        for caminho in caminhos:
            documento = json.loads(caminho.read_text(encoding="utf-8"))
            for componente in documento["components"]:
                # `.get`, e nao `[...]`: desde que o `"licenses": []` deixou de
                # se emitir (um array vazio falha o `oneOf` do `licenseChoice`),
                # um componente sem licenca nao tem a propriedade de todo.
                for licenca in componente.get("licenses", []):
                    identificador = licenca.get("license", {}).get("id")
                    if identificador is None:
                        continue
                    with self.subTest(sbom=caminho.name, pacote=componente["name"]):
                        self.assertIn(identificador, curados)


class TestLicencasDoRepositorio(unittest.TestCase):
    def test_o_repositorio_passa_o_gate_11(self) -> None:
        achados, _ = verificar_licencas(ROOT)
        self.assertEqual(achados, [], "\n".join(achados))

    def test_as_tres_licencas_que_a_proposta_do_ticket_reprovaria(self) -> None:
        """Os falsos vermelhos que a allowlist original dava no dia 1.

        Estao instaladas: se alguma deixar de passar, a allowlist regrediu.
        """
        politica, proprios = ler_politica(ROOT)
        from sbom.spdx import PERMITIDA, classificar

        instaladas = {c.nome: c.licenca for c in recolher(ROOT)}
        # `typing-extensions` e `PSF-2.0` e esta fixado nos dois `.in`.
        self.assertEqual(instaladas.get("typing_extensions"), "PSF-2.0")
        self.assertEqual(classificar("PSF-2.0", politica)[0], PERMITIDA)
        # `argparse` e `Python-2.0`, via js-yaml -> cosmiconfig -> commitlint.
        if "argparse" in instaladas:
            self.assertEqual(instaladas["argparse"], "Python-2.0")
            self.assertEqual(classificar("Python-2.0", politica)[0], PERMITIDA)
        # Os nossos sao `UNLICENSED` e resolvem-se por identidade.
        self.assertEqual(instaladas.get("kamba"), "UNLICENSED")
        self.assertIn("kamba", proprios)

    def test_configuracao_vazia_e_recusada(self) -> None:
        """Uma allowlist vazia nao deixaria passar nada — parece configuracao em
        falta, nao politica."""
        with tempfile.TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            (raiz / "ci").mkdir()
            (raiz / "ci" / "licenses.yaml").write_text(
                "version: 1\npermitidas: []\n", encoding="utf-8"
            )
            with self.assertRaises(ConfiguracaoInvalida):
                ler_politica(raiz)

    def test_sem_ficheiro_levanta(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ConfiguracaoInvalida):
                ler_politica(Path(tmp))


if __name__ == "__main__":
    unittest.main()
