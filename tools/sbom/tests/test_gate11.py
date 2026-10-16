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
        self.directas, self.snapshots = pnpm_lock.ler(ROOT / "pnpm-lock.yaml")

    #: Quantas dependencias cada servico Node carrega, pelo fecho do lockfile.
    #: Lista fechada: um servico que ganhe uma dependencia muda o seu numero
    #: aqui, e e isso que faz a entrada de uma dependencia nova ser uma decisao
    #: e nao um acidente. O `worker-canal` passou de 2 a 19 com o KAM-005: o
    #: publicador leva `pg`, e o `pg` leva dezasseis.
    DEPENDENCIAS_POR_SERVICO = {
        "services/gwy": 2,
        "services/worker-canal": 19,
        "services/com": 2,
        "services/onboarding-web": 2,
    }

    def test_os_servicos_node_carregam_o_que_declaram(self) -> None:
        for servico, quantas in self.DEPENDENCIAS_POR_SERVICO.items():
            with self.subTest(servico=servico):
                fecho = pnpm_lock.fecho(servico, self.directas, self.snapshots)
                self.assertEqual(
                    {x.split("@")[0] or "@" + x.split("@")[1] for x in fecho} & {"hono"},
                    {"hono"},
                )
                self.assertEqual(len(fecho), quantas, sorted(fecho))

    def test_o_fecho_do_publicador_nao_atravessa_o_workspace(self) -> None:
        """KAM-005 encontrou a lacuna do KAM-133 pelo lado de dentro.

        O publicador vive em `services/worker-canal` e usa `bullmq` e `ioredis`,
        que sao dependencias de `@kamba/core-ts` — e `@kamba/core-ts` entra por
        `workspace:*`. O fecho **nao atravessa** essa ligacao, pelo que o SBOM
        do servico nao mostra nem o `bullmq` nem o `ioredis`: mostra o `pg`, que
        e dependencia directa dele.

        Isto nao e um defeito deste teste — e a lacuna que o **KAM-133** paga
        («SBOM por servico a atravessar as dependencias `link:` do
        *workspace*»). Fica fixado aqui para que, no dia em que o KAM-133 a
        fechar, este teste **falhe** e alguem actualize as contagens em vez de
        o SBOM mudar em silencio.
        """
        fecho = pnpm_lock.fecho(
            "services/worker-canal", self.directas, self.snapshots
        )
        nomes = {x.rsplit("@", 1)[0] for x in fecho}
        self.assertIn("pg", nomes, sorted(nomes))
        for pacote in ("bullmq", "ioredis"):
            with self.subTest(pacote=pacote):
                self.assertNotIn(pacote, nomes, "o KAM-133 fechou: actualize as contagens")

        # E aparecem no fecho do pacote que os declara.
        do_core = {
            x.rsplit("@", 1)[0]
            for x in pnpm_lock.fecho("packages/core-ts", self.directas, self.snapshots)
        }
        for pacote in ("bullmq", "ioredis"):
            with self.subTest(pacote=pacote, alvo="packages/core-ts"):
                self.assertIn(pacote, do_core, sorted(do_core))

    def test_a_raiz_carrega_o_fecho_das_devdependencies(self) -> None:
        """O `@commitlint/cli` tem tres pares; sem normalizar as chaves, o fecho
        parava nele e dava 12 em vez de ~74."""
        fecho = pnpm_lock.fecho(".", self.directas, self.snapshots)
        self.assertGreater(len(fecho), 60, sorted(fecho)[:5])

    def test_o_alvo_do_conjunto_cobre_mais_do_que_um_servico(self) -> None:
        todos = recolher(ROOT)
        conjunto = componentes_do_alvo(ROOT, "kamba", todos)
        servico = componentes_do_alvo(ROOT, "services/gwy", todos)
        self.assertGreater(len(conjunto), len(servico) * 5)

    def test_um_servico_inclui_o_seu_proprio_pacote(self) -> None:
        todos = recolher(ROOT)
        nomes = {c.nome for c in componentes_do_alvo(ROOT, "services/gwy", todos)}
        self.assertIn("@kamba/gwy", nomes)
        self.assertNotIn("@kamba/com", nomes, "o SBOM do gwy nao leva o com")


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
                for licenca in componente["licenses"]:
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
