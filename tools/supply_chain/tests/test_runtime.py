"""Sem instalacao em runtime, so do lockfile, e so de leitura (criterio 4)."""

from __future__ import annotations

import unittest

from supply_chain import dockerfile, runtime
from supply_chain.runtime import instaladores_em

from .base import ComArvore

COMPOSE = "infra/compose/docker-compose.dev.yml"
DOCKERFILE = "services/gwy/Dockerfile"


class TestInstaladores(unittest.TestCase):
    def test_o_que_e_instalacao(self) -> None:
        for comando, ferramenta in (
            ("pip install litellm", "pip"),
            ("pip3 install -r requirements.txt", "pip"),
            ("python -m pip install x", "pip"),
            ("python3.12 -m pip install x", "pip"),
            (".venv/bin/python -m pip install x", "pip"),
            ("$(VENV_PYTHON) -m pip install --quiet x", "pip"),
            ("pip download x", "pip"),
            ("uv pip install x", "uv"),
            ("uv sync", "uv"),
            ("poetry install", "poetry"),
            ("pipx run black", "pipx"),
            ("npm i", "npm"),
            ("npm install", "npm"),
            ("npm ci", "npm"),
            ("npx cowsay", "npm"),
            ("pnpm install", "pnpm"),
            ("pnpm add zod", "pnpm"),
            ("pnpm dlx x", "pnpm"),
            ("yarn", "yarn"),
            ("yarn add x", "yarn"),
            ("bun install", "bun"),
            ("sudo pip install x", "pip"),
            ("exec pip install x", "pip"),
            ("PIP_NO_CACHE_DIR=1 pip install x", "pip"),
            ("env A=1 B=2 npm i", "npm"),
            ("cd /app && npm i", "npm"),
            ("true; pip install x", "pip"),
            ("test -f x || pip install x", "pip"),
            ("sh -c 'pip install x && python app.py'", "pip"),
            ('bash -lc "npm i && node server.js"', "npm"),
            ("/bin/sh -c pip install x", "pip"),
            ("echo $(pip install x)", "pip"),
            ("echo `npm i`", "npm"),
            ("(pip install x)", "pip"),
            ("node server.js & npm i", "npm"),
        ):
            with self.subTest(comando=comando):
                self.assertEqual([f for f, _ in instaladores_em(comando)], [ferramenta])

    def test_o_que_nao_e(self) -> None:
        for comando in (
            "python -m kamba_agr",
            "node services/gwy/src/server.ts",
            "pnpm run build",
            "pnpm -r run test",
            "npm run start",
            "npm test",
            "corepack enable",
            "echo pip install x",
            "pip --version",
            "pipenv --version",
            "grep 'pip install' README.md",
            "make install",
            "uvicorn app:app",
            "yarn run build",
        ):
            with self.subTest(comando=comando):
                self.assertEqual(instaladores_em(comando), [])


class TestDockerfile(unittest.TestCase):
    def test_continuacoes_e_comentarios(self) -> None:
        lidas = dockerfile.instrucoes(
            "# comentario\nFROM a\nRUN um \\\n    # a meio\n    dois \\\n    tres\nCMD x\n"
        )
        self.assertEqual(
            [(i.nome, i.argumentos, i.linha) for i in lidas],
            [("FROM", "a", 2), ("RUN", "um dois tres", 3), ("CMD", "x", 7)],
        )

    def test_heredoc_fica_dentro_do_run(self) -> None:
        lidas = dockerfile.instrucoes("FROM a\nRUN <<EOF\npip install x\nEOF\nCMD y\n")
        self.assertEqual([i.nome for i in lidas], ["FROM", "RUN", "CMD"])
        self.assertIn("pip install x", lidas[1].argumentos)

    def test_escape_alternativo(self) -> None:
        lidas = dockerfile.instrucoes("# escape=`\nFROM a\nRUN um `\n  dois\n")
        self.assertEqual(lidas[1].argumentos, "um dois")

    def test_ultima_linha_com_continuacao_por_fechar(self) -> None:
        lidas = dockerfile.instrucoes("FROM a\nRUN um \\")
        self.assertEqual([(i.nome, i.argumentos) for i in lidas], [("FROM", "a"), ("RUN", "um")])

    def test_syntax_so_antes_da_primeira_instrucao(self) -> None:
        self.assertEqual(dockerfile.directiva_syntax("# x\n# syntax=docker/dockerfile:1\nFROM a\n"), ("docker/dockerfile:1", 2))
        self.assertIsNone(dockerfile.directiva_syntax("FROM a\n# syntax=docker/dockerfile:1\n"))
        self.assertIsNone(dockerfile.directiva_syntax("\n# so comentarios\n"))


class TestRuntime(ComArvore):
    def regras_de(self) -> list[str]:
        return self.regras(runtime.verificar(self.raiz)[0])

    def test_o_minimo_passa(self) -> None:
        achados, contagem = runtime.verificar(self.raiz)
        self.assertEqual([str(a) for a in achados], [])
        self.assertEqual(contagem["dockerfiles"], 1)
        self.assertEqual(contagem["servicos"], 3)
        # o `pnpm install` do Dockerfile e o do Makefile
        self.assertEqual(contagem["instalacoes_de_build"], 2)

    # ----------------------------------------------- instalacao em runtime

    def test_cmd_e_entrypoint_do_dockerfile(self) -> None:
        for instrucao in (
            'CMD ["sh", "-c", "pip install litellm && python -m x"]',
            "CMD pip install litellm && python -m x",
            'ENTRYPOINT ["npm", "i"]',
            "ENTRYPOINT npx serve",
            "HEALTHCHECK --interval=5s CMD pip install x || exit 1",
        ):
            with self.subTest(instrucao=instrucao):
                original = self.ler(DOCKERFILE)
                self.trocar(DOCKERFILE, 'CMD ["node", "services/gwy/src/server.ts"]', instrucao)
                try:
                    self.assertEqual(self.regras_de(), ["instalacao-em-runtime"])
                finally:
                    self.escrever(DOCKERFILE, original)

    def test_script_de_arranque_chamado_pelo_dockerfile(self) -> None:
        self.trocar(DOCKERFILE, 'CMD ["node", "services/gwy/src/server.ts"]', 'ENTRYPOINT ["/app/arrancar.sh"]')
        self.escrever("services/gwy/arrancar.sh", "#!/bin/sh\nset -e\n# pip install comentado\npip install \\\n  litellm\nexec node server.js\n")
        achados, _ = runtime.verificar(self.raiz)
        self.assertEqual(self.regras(achados), ["instalacao-em-runtime"])
        self.assertEqual((achados[0].ficheiro, achados[0].linha), ("services/gwy/arrancar.sh", 4))

    def test_script_com_nome_de_arranque_mesmo_sem_ninguem_o_chamar(self) -> None:
        for nome in ("entrypoint.sh", "docker-entrypoint.sh", "start.sh", "arranque-agr.sh"):
            with self.subTest(nome=nome):
                self.escrever(f"services/gwy/{nome}", "#!/bin/sh\nnpm i\n")
                try:
                    self.assertEqual(self.regras_de(), ["instalacao-em-runtime"])
                finally:
                    (self.raiz / "services/gwy" / nome).unlink()

    def test_script_que_nao_e_de_arranque_fica_de_fora(self) -> None:
        self.escrever("tools/preparar-ambiente.sh", "#!/bin/sh\nnpm i\n")
        self.assertEqual(self.regras_de(), [])

    def test_command_e_entrypoint_do_compose(self) -> None:
        for trecho in (
            '    command: ["sh", "-c", "npm i && node x.js"]\n',
            "    command: sh -c 'pip install x && python -m y'\n",
            "    entrypoint:\n      - sh\n      - -c\n      - pnpm install && node x.js\n",
            "    command: >-\n      sh -c 'npm install\n      && node x.js'\n",
        ):
            with self.subTest(trecho=trecho):
                original = self.ler(COMPOSE)
                self.trocar(COMPOSE, "  gwy:\n", "  gwy:\n" + trecho)
                try:
                    self.assertEqual(self.regras_de(), ["instalacao-em-runtime"])
                finally:
                    self.escrever(COMPOSE, original)

    def test_command_herdado_por_ancora(self) -> None:
        self.trocar(COMPOSE, "  restart: unless-stopped\n", "  restart: unless-stopped\n  command: sh -c 'npm i && node x'\n")
        achados, _ = runtime.verificar(self.raiz)
        self.assertEqual(self.regras(achados), ["instalacao-em-runtime"])
        self.assertIn("services.gwy.command", achados[0].mensagem)

    def test_healthcheck_do_compose(self) -> None:
        self.trocar(COMPOSE, "        - node\n        - -e\n", "        - sh\n        - -c\n        - npx x;\n")
        self.assertEqual(self.regras_de(), ["instalacao-em-runtime"])

    def test_scripts_de_arranque_do_package_json(self) -> None:
        self.trocar("services/gwy/package.json", '"start": "node src/server.ts"', '"start": "npm install && node src/server.ts"')
        achados, _ = runtime.verificar(self.raiz)
        self.assertEqual(self.regras(achados), ["instalacao-em-runtime"])
        self.assertIn("scripts.start", achados[0].mensagem)

    def test_outros_scripts_do_package_json_nao_sao_arranque(self) -> None:
        self.trocar("services/gwy/package.json", '"start": "node src/server.ts"', '"start": "node src/server.ts", "preparar": "npm install"')
        self.assertEqual(self.regras_de(), [])

    # ------------------------------------------ instalacao fora do lockfile

    def test_run_do_dockerfile(self) -> None:
        for instrucao in (
            "RUN pip install litellm",
            "RUN python -m pip install --no-deps -r r.txt",
            "RUN pnpm install --frozen-lockfile",
            "RUN pnpm install --ignore-scripts",
            "RUN pnpm add zod",
            "RUN npm ci",
            "RUN npm install",
            "RUN npm i --ignore-scripts",
            "RUN yarn install --frozen-lockfile",
            "RUN apt-get update && pip install x",
            "RUN --mount=type=cache,target=/root/.cache pip install x",
            'RUN ["pip", "install", "x"]',
            "RUN <<EOF\npip install x\nEOF",
        ):
            with self.subTest(instrucao=instrucao):
                original = self.ler(DOCKERFILE)
                self.trocar(DOCKERFILE, "RUN pnpm install --frozen-lockfile --ignore-scripts", instrucao)
                try:
                    self.assertEqual(self.regras_de(), ["instalacao-fora-do-lockfile"])
                finally:
                    self.escrever(DOCKERFILE, original)

    def test_instalacoes_de_build_que_vem_do_lockfile(self) -> None:
        for instrucao in (
            "RUN python -m pip install --require-hashes --no-deps -r r.txt",
            "RUN npm ci --ignore-scripts",
            "RUN pnpm i --frozen-lockfile --ignore-scripts --prod",
        ):
            with self.subTest(instrucao=instrucao):
                original = self.ler(DOCKERFILE)
                self.trocar(DOCKERFILE, "RUN pnpm install --frozen-lockfile --ignore-scripts", instrucao)
                try:
                    self.assertEqual(self.regras_de(), [])
                finally:
                    self.escrever(DOCKERFILE, original)

    def test_receita_do_makefile(self) -> None:
        self.escrever("Makefile", "venv:\n\t@$(VENV_PYTHON) -m pip install --quiet --upgrade pip\n")
        achados, _ = runtime.verificar(self.raiz)
        self.assertEqual([(a.regra, a.ficheiro, a.linha) for a in achados], [("instalacao-fora-do-lockfile", "Makefile", 2)])

    def test_o_makefile_ignora_o_que_nao_e_receita(self) -> None:
        self.escrever("Makefile", "# pip install x\nX := pip install x\nalvo:\n\t@# pip install x\n\t@echo \"corra pnpm install\"\n")
        self.assertEqual(self.regras_de(), [])

    def test_passo_de_workflow(self) -> None:
        self.trocar(".github/workflows/ci.yaml", "          make ci-1\n", "          make ci-1\n          pip install cosign\n")
        achados, _ = runtime.verificar(self.raiz)
        self.assertEqual(self.regras(achados), ["instalacao-fora-do-lockfile"])
        self.trocar(".github/workflows/ci.yaml", "          pip install cosign\n", "")
        self.trocar(".github/workflows/ci.yaml", "      - run: make ci-2", "      - run: npm install -g x")
        self.assertEqual(self.regras_de(), ["instalacao-fora-do-lockfile"])

    # ----------------------------------------------------- so de leitura

    def test_servico_sem_read_only(self) -> None:
        self.trocar(COMPOSE, "    read_only: true\n    networks:\n      - data\n", "    networks:\n      - data\n")
        achados, _ = runtime.verificar(self.raiz)
        self.assertEqual(self.regras(achados), ["fs-so-de-leitura"])
        self.assertIn("`postgres`", achados[0].mensagem)

    def test_read_only_false_ou_outra_coisa(self) -> None:
        for valor in ("false", "no", '"false"', "${RO:-true}"):
            with self.subTest(valor=valor):
                original = self.ler(COMPOSE)
                self.trocar(COMPOSE, "    read_only: true\n    networks:\n      - data\n", f"    read_only: {valor}\n    networks:\n      - data\n")
                try:
                    self.assertEqual(self.regras_de(), ["fs-so-de-leitura"])
                finally:
                    self.escrever(COMPOSE, original)

    def test_read_only_retirado_da_ancora(self) -> None:
        self.trocar(COMPOSE, "  restart: unless-stopped\n  read_only: true\n", "  restart: unless-stopped\n")
        achados, _ = runtime.verificar(self.raiz)
        self.assertEqual(self.regras(achados), ["fs-so-de-leitura"])
        self.assertIn("`gwy`", achados[0].mensagem)

    def test_servico_que_desfaz_o_que_a_ancora_da(self) -> None:
        self.trocar(COMPOSE, "    <<: *defaults\n", "    <<: *defaults\n    read_only: false\n")
        self.assertEqual(self.regras_de(), ["fs-so-de-leitura"])

    def test_extends_nao_se_segue(self) -> None:
        self.trocar(COMPOSE, "    <<: *defaults\n", "    <<: *defaults\n    extends:\n      file: outro.yml\n      service: base\n")
        self.assertEqual(self.regras_de(), ["fs-so-de-leitura"])

    def test_compose_com_outro_nome_tambem_conta(self) -> None:
        self.escrever("ops/stack.yml", "services:\n  x:\n    image: a\n")
        achados, _ = runtime.verificar(self.raiz)
        self.assertEqual([(a.regra, a.ficheiro) for a in achados], [("fs-so-de-leitura", "ops/stack.yml")])


if __name__ == "__main__":
    unittest.main()
