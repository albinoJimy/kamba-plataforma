"""Regressao dos achados da revisao adversarial (ANALISE-10).

A primeira versao destes verificadores passou os seus 189 testes e o seu
canario, e a revisao fez passar 78 defeitos em 86: os testes cobriam as formas
que o autor imaginou, e os verificadores casavam formas literais. Cada teste
aqui e uma forma **equivalente** que passava, com o identificador do achado.
"""

from __future__ import annotations

import re
import unittest

from supply_chain import ci_chaves, dockerfile, egress, imagens, renovate, runtime
from supply_chain.runtime import instaladores_em

from .base import D_NODE, D_PG, ROOT, ComArvore

COMPOSE = "infra/compose/docker-compose.dev.yml"
DOCKERFILE = "services/gwy/Dockerfile"
INVENTARIO = "ci/supply-chain/imagens.yaml"
WORKFLOW = ".github/workflows/ci.yaml"


class TestB1ComposeNoutrasFormas(ComArvore):
    """`image: litellm:latest` escrito de maneiras que o `docker compose` aceita."""

    def regras_de(self) -> set[str]:
        return set(self.regras(imagens.verificar(self.raiz)[0]))

    def test_estilo_de_fluxo(self) -> None:
        self.escrever("infra/stack.yml", "services: {llm: {image: litellm:latest}}\n")
        self.assertIn("ficheiro-ilegivel", self.regras_de())

    def test_chave_entre_aspas(self) -> None:
        for aspas in ('"', "'"):
            with self.subTest(aspas=aspas):
                self.escrever("infra/stack.yml", f"{aspas}services{aspas}:\n  llm:\n    image: litellm:latest\n")
                self.assertIn("imagem-sem-digest", self.regras_de())

    def test_documento_indentado(self) -> None:
        self.escrever("infra/stack.yml", "  services:\n    llm:\n      image: litellm:latest\n")
        self.assertIn("imagem-sem-digest", self.regras_de())

    def test_json(self) -> None:
        self.escrever("infra/compose.json", '{"services": {"llm": {"image": "litellm:latest"}}}\n')
        self.assertIn("ficheiro-ilegivel", self.regras_de())
        self.escrever("infra/compose.json", "{}")
        (self.raiz / "infra/compose.json").unlink()
        self.escrever("infra/pilha.json", '{"services": {"llm": {"image": "litellm:latest"}}}\n')
        self.assertIn("ficheiro-ilegivel", self.regras_de())

    def test_bom(self) -> None:
        self.escrever("infra/compose/docker-compose.prod.yml", "\ufeffservices:\n  llm:\n    image: litellm:latest\n")
        self.assertIn("imagem-sem-digest", self.regras_de())

    def test_compose_pelo_nome_sem_servicos_nao_passa_calado(self) -> None:
        for corpo in ("version: '3'\n", "servicos:\n  x:\n    image: a\n", "services:\n"):
            with self.subTest(corpo=corpo):
                self.escrever("infra/compose/docker-compose.prod.yml", corpo)
                self.assertIn("ficheiro-ilegivel", self.regras_de())

    def test_include_nao_e_seguido_e_por_isso_e_achado(self) -> None:
        self.escrever(COMPOSE, "include:\n  - outro.yml\n" + self.ler(COMPOSE))
        self.assertIn("ficheiro-ilegivel", self.regras_de())

    def test_dockerfile_inline_e_additional_contexts(self) -> None:
        for chave, valor in (
            ("dockerfile_inline", "FROM litellm:latest"),
            ("additional_contexts", "\n        base: docker-image://litellm:latest"),
        ):
            with self.subTest(chave=chave):
                original = self.ler(COMPOSE)
                self.trocar(COMPOSE, "      dockerfile: services/gwy/Dockerfile\n", f"      dockerfile: services/gwy/Dockerfile\n      {chave}: {valor}\n")
                try:
                    self.assertEqual(self.regras_de(), {"imagem-nao-resolvida"})
                finally:
                    self.escrever(COMPOSE, original)

    def test_build_arg_em_lista_sem_valor_herda_o_ambiente(self) -> None:
        self.trocar(COMPOSE, "        COMMIT: ${COMMIT:-unknown}", "        - NODE_IMAGE")
        self.assertEqual(self.regras_de(), {"imagem-nao-resolvida"})

    def test_m8_manifesto_de_kubernetes(self) -> None:
        self.escrever(
            "infra/k8s/s3.yaml",
            "kind: Deployment\nspec:\n  template:\n    spec:\n      containers:\n        - name: s3\n          image: minio/minio:latest\n",
        )
        achados, _ = imagens.verificar(self.raiz)
        self.assertEqual([(a.regra, a.ficheiro, a.linha) for a in achados], [("imagem-sem-digest", "infra/k8s/s3.yaml", 7)])

    def test_m8_valores_de_helm_com_a_imagem_partida(self) -> None:
        self.escrever("infra/helm/values.yaml", "image: {repository: minio/minio, tag: latest}\n")
        self.assertEqual(self.regras_de(), {"imagem-nao-resolvida"})

    def test_yaml_sem_imagens_nao_e_lido_nem_da_achado(self) -> None:
        self.escrever("ops/qualquer.yaml", "a: [1, 2\n")  # ilegivel, mas nao fala de imagens
        self.assertEqual(self.regras_de(), set())

    def test_pasta_dist_ja_nao_esconde_nada(self) -> None:
        self.escrever("infra/dist/Dockerfile", "FROM litellm:latest\n")
        self.assertIn("imagem-sem-digest", self.regras_de())


class TestB2Dockerfile(ComArvore):
    def test_heredoc_falso_nao_engole_o_resto(self) -> None:
        for linha in ("RUN echo $((1<<n))", 'RUN cat <<<"x"', "RUN test $[1<<2] -gt 0"):
            with self.subTest(linha=linha):
                lidas = dockerfile.instrucoes(f"FROM a\n{linha}\nFROM b AS segundo\nCMD x\n")
                self.assertEqual([i.nome for i in lidas], ["FROM", "RUN", "FROM", "CMD"])

    def test_heredoc_verdadeiro_continua_a_ser_lido(self) -> None:
        for abertura in ("<<EOF", "<<-EOF", '<<"EOF"', "<<'EOF'", "cat <<EOF > /x"):
            with self.subTest(abertura=abertura):
                lidas = dockerfile.instrucoes(f"FROM a\nRUN {abertura}\npip install x\nEOF\nCMD y\n")
                self.assertEqual([i.nome for i in lidas], ["FROM", "RUN", "CMD"])
                self.assertIn("pip install x", lidas[1].argumentos)

    def test_heredoc_por_fechar_levanta(self) -> None:
        with self.assertRaises(dockerfile.DockerfileIlegivel):
            dockerfile.instrucoes("FROM a\nRUN <<EOF\necho x\nCMD y\n")

    def test_o_caso_completo_da_revisao(self) -> None:
        self.trocar(
            DOCKERFILE, "USER node\n",
            'RUN echo $((1<<n))\nFROM litellm:latest AS segundo\nCMD ["sh", "-c", "pip install litellm"]\nUSER node\n',
        )
        regras = set(self.regras(imagens.verificar(self.raiz)[0])) | set(self.regras(runtime.verificar(self.raiz)[0]))
        self.assertLessEqual({"imagem-sem-digest", "instalacao-em-runtime"}, regras)

    def test_dockerfile_ilegivel_e_achado_e_nao_parte_o_runtime(self) -> None:
        self.trocar(DOCKERFILE, "USER node\n", "RUN <<FIM\necho x\nUSER node\n")
        self.assertIn("ficheiro-ilegivel", self.regras(imagens.verificar(self.raiz)[0]))
        runtime.verificar(self.raiz)  # nao levanta

    def test_nomes_de_dockerfile(self) -> None:
        from pathlib import Path

        for nome in ("Dockerfile", "dockerfile", "DOCKERFILE", "Dockerfile-base", "Dockerfile_dev",
                     "Dockerfile.prod", "base.Dockerfile", "base.dockerfile", "Containerfile", "containerfile.dev"):
            with self.subTest(nome=nome):
                self.assertTrue(dockerfile.e_dockerfile(Path("x") / nome))
        for nome in ("Dockerfile.md", "dockerfile.py", "test_dockerfile.py", "docker-compose.yml", "README.md", ".dockerignore"):
            with self.subTest(nome=nome):
                self.assertFalse(dockerfile.e_dockerfile(Path("x") / nome))

    def test_onbuild(self) -> None:
        self.trocar(DOCKERFILE, "USER node\n", "ONBUILD COPY --from=litellm:latest /a /b\nONBUILD RUN pip install x\nUSER node\n")
        self.assertIn("imagem-sem-digest", self.regras(imagens.verificar(self.raiz)[0]))
        self.assertEqual(self.regras(runtime.verificar(self.raiz)[0]), ["instalacao-fora-do-lockfile"])


class TestB3Instaladores(unittest.TestCase):
    def test_as_variantes_que_passavam(self) -> None:
        for comando, ferramenta in (
            ("pip --no-cache-dir install litellm", "pip"),
            ("/usr/local/bin/pip install litellm", "pip"),
            ("$(VENV)/bin/pip install --quiet --upgrade pip", "pip"),
            (".venv/bin/pip3 install x", "pip"),
            ("python -u -m pip install x", "pip"),
            ("python -mpip install x", "pip"),
            ("python3 -I -m pip --quiet install x", "pip"),
            ("sh -e -c 'pip install x'", "pip"),
            ("bash -eu -o pipefail -c 'pip install x'", "pip"),
            ("if true; then pip install litellm; fi", "pip"),
            ("if [ ! -d node_modules ]; then npm i; fi; node x.js", "npm"),
            ("timeout 300 pip install x", "pip"),
            ("timeout -s KILL 5m pip install x", "pip"),
            ("cat reqs.txt | xargs pip install", "pip"),
            ("cat reqs.txt | xargs -n 1 pip install", "pip"),
            ("nohup npm i", "npm"),
            ("sudo -H pip install requests", "pip"),
            ("sudo -u node npm i", "npm"),
            ("gosu node npm install", "npm"),
            ("corepack pnpm add zod", "pnpm"),
            ("npm --prefix /app install left-pad", "npm"),
            ("pnpm --filter gwy add zod", "pnpm"),
            ("pnpm -C /app install", "pnpm"),
            ("pnpm rebuild", "pnpm"),
            ("npm rebuild", "npm"),
            ("while ! pip install x; do sleep 1; done", "pip"),
            ("! pip install x", "pip"),
            ("{ pip install x; }", "pip"),
            ("@$(VENV_PYTHON) -m pip install x", "pip"),
            ("python -m ensurepip", "pip"),
            ("uv run app.py", "uv"),
            ("yarn --frozen-lockfile", "yarn"),
        ):
            with self.subTest(comando=comando):
                self.assertEqual([f for f, _ in instaladores_em(comando)], [ferramenta])

    def test_continua_a_nao_dar_falsos_positivos(self) -> None:
        for comando in (
            "python -m kamba_agr",
            "python -m http.server",
            "pip --version",
            "pip list",
            "pip freeze",
            "npm run install-hooks",
            "npm --prefix /app run build",
            "pnpm -r run test",
            "pnpm --filter gwy run build",
            "echo pip install x",
            "grep -r 'npm i' docs",
            "timeout 5 node server.js",
            "sudo -u node node server.js",
            "corepack enable",
            "if true; then node x.js; fi",
            "yarn build",
            "uv --version",
            "pipeline install",
            "install -m 0755 a b",
            "make install",
        ):
            with self.subTest(comando=comando):
                self.assertEqual(instaladores_em(comando), [])


class TestB3Arranque(ComArvore):
    CMD = 'CMD ["node", "services/gwy/src/server.ts"]'

    def regras_de(self) -> list[str]:
        return self.regras(runtime.verificar(self.raiz)[0])

    def test_o_minimo_continua_a_passar(self) -> None:
        self.assertEqual([str(a) for a in runtime.verificar(self.raiz)[0]], [])

    def test_cmd_em_forma_shell_com_controlo(self) -> None:
        self.trocar(DOCKERFILE, self.CMD, "CMD if [ ! -d node_modules ]; then npm i; fi; node services/gwy/src/server.ts")
        self.assertEqual(self.regras_de(), ["instalacao-em-runtime"])

    def test_script_sem_extensao(self) -> None:
        self.trocar(DOCKERFILE, self.CMD, 'ENTRYPOINT ["/app/docker-entrypoint"]')
        self.escrever("services/gwy/docker-entrypoint", "#!/bin/sh\nnpm i\nexec node server.js\n")
        achados, _ = runtime.verificar(self.raiz)
        self.assertEqual([(a.regra, a.ficheiro, a.linha) for a in achados], [("instalacao-em-runtime", "services/gwy/docker-entrypoint", 2)])

    def test_cadeia_de_scripts(self) -> None:
        for chamada in (". /app/prepara.sh", "source ./prepara.sh", "sh /app/prepara.sh", "/app/prepara.sh", "exec /app/prepara.sh"):
            with self.subTest(chamada=chamada):
                self.escrever(DOCKERFILE, self.ler(DOCKERFILE).replace(self.CMD, 'ENTRYPOINT ["/app/entrypoint.sh"]'))
                self.escrever("services/gwy/entrypoint.sh", f"#!/bin/sh\nset -e\n{chamada}\nexec node server.js\n")
                self.escrever("services/gwy/prepara.sh", "#!/bin/sh\ntimeout 60 python -u -m pip install x\n")
                achados, _ = runtime.verificar(self.raiz)
                self.assertEqual([(a.regra, a.ficheiro) for a in achados], [("instalacao-em-runtime", "services/gwy/prepara.sh")])

    def test_cadeia_em_ciclo_termina(self) -> None:
        self.trocar(DOCKERFILE, self.CMD, 'ENTRYPOINT ["/app/a.sh"]')
        self.escrever("services/gwy/a.sh", "#!/bin/sh\n. /app/b.sh\n")
        self.escrever("services/gwy/b.sh", "#!/bin/sh\n. /app/a.sh\n")
        self.assertEqual(self.regras_de(), [])

    def test_script_que_nao_se_encontra(self) -> None:
        for instrucao in ('CMD ["/opt/kamba/lanca.sh"]', 'ENTRYPOINT ["./bin/arranca"]', "CMD /app/lanca.sh --porta 3000", 'CMD ["sh", "/app/lanca.sh"]'):
            with self.subTest(instrucao=instrucao):
                original = self.ler(DOCKERFILE)
                self.trocar(DOCKERFILE, self.CMD, instrucao)
                try:
                    self.assertEqual(self.regras_de(), ["arranque-nao-verificavel"])
                finally:
                    self.escrever(DOCKERFILE, original)

    def test_executaveis_do_sistema_e_interpretadores_nao_se_exigem(self) -> None:
        for instrucao in (
            'CMD ["/usr/local/bin/node", "services/gwy/src/server.ts"]',
            'CMD ["/usr/bin/tini", "--", "node", "services/gwy/src/server.ts"]',
            'ENTRYPOINT ["python", "-m", "kamba_agr"]',
            "CMD node services/gwy/src/server.ts",
        ):
            with self.subTest(instrucao=instrucao):
                original = self.ler(DOCKERFILE)
                self.trocar(DOCKERFILE, self.CMD, instrucao)
                try:
                    self.assertEqual(self.regras_de(), [])
                finally:
                    self.escrever(DOCKERFILE, original)

    def test_script_encontrado_noutra_pasta_pelo_nome(self) -> None:
        self.trocar(DOCKERFILE, self.CMD, 'CMD ["/opt/kamba/lanca.sh"]')
        self.escrever("services/gwy/scripts/lanca.sh", "#!/bin/sh\npnpm install\n")
        achados, _ = runtime.verificar(self.raiz)
        self.assertEqual([(a.regra, a.ficheiro) for a in achados], [("instalacao-em-runtime", "services/gwy/scripts/lanca.sh")])

    def test_arranque_por_script_do_package_json(self) -> None:
        for cmd in ('CMD ["pnpm", "run", "arranque"]', "CMD npm run arranque", 'CMD ["yarn", "arranque"]', "CMD pnpm --filter gwy run arranque"):
            with self.subTest(cmd=cmd):
                original_d, original_p = self.ler(DOCKERFILE), self.ler("services/gwy/package.json")
                self.trocar(DOCKERFILE, self.CMD, cmd)
                self.trocar("services/gwy/package.json", '"start": "node src/server.ts"', '"start": "node src/server.ts", "arranque": "npm i && node src/server.ts"')
                try:
                    achados, _ = runtime.verificar(self.raiz)
                finally:
                    self.escrever(DOCKERFILE, original_d)
                    self.escrever("services/gwy/package.json", original_p)
                self.assertEqual(self.regras(achados), ["instalacao-em-runtime"])
                self.assertIn("scripts.arranque", achados[0].mensagem)

    def test_ganchos_do_compose(self) -> None:
        self.trocar(COMPOSE, "  gwy:\n", "  gwy:\n    post_start:\n      - command: [\"sh\", \"-c\", \"npm i\"]\n")
        achados, _ = runtime.verificar(self.raiz)
        self.assertEqual(self.regras(achados), ["instalacao-em-runtime"])

    def test_o_healthcheck_em_javascript_nao_da_falso_vermelho(self) -> None:
        """O `node -e '...'` do compose real tem `/`, `(` e `;` dentro do JavaScript."""
        achados, _ = runtime.verificar(ROOT)
        self.assertEqual([str(a) for a in achados], [])

    def test_build_as_variantes_que_passavam(self) -> None:
        for instrucao in (
            "RUN pip --no-cache-dir install requests",
            "RUN /usr/local/bin/pip install requests",
            "RUN npm --prefix /app install left-pad",
            "RUN pnpm install --frozen-lockfile --ignore-scripts && pnpm rebuild",
            "RUN pnpm install --frozen-lockfile --ignore-scripts; npm rebuild",
        ):
            with self.subTest(instrucao=instrucao):
                original = self.ler(DOCKERFILE)
                self.trocar(DOCKERFILE, "RUN pnpm install --frozen-lockfile --ignore-scripts", instrucao)
                try:
                    self.assertEqual(self.regras_de(), ["instalacao-fora-do-lockfile"])
                finally:
                    self.escrever(DOCKERFILE, original)

    def test_o_makefile_pelo_caminho_do_venv(self) -> None:
        """A forma a um passo de distancia da que o proprio `Makefile` tinha."""
        self.escrever("Makefile", "venv:\n\t@$(VENV)/bin/pip install --quiet --upgrade pip\n")
        self.assertEqual(self.regras_de(), ["instalacao-fora-do-lockfile"])

    def test_workflow_com_sudo(self) -> None:
        self.trocar(WORKFLOW, "      - run: make ci-2", "      - run: sudo -H pip install requests")
        self.assertEqual(self.regras_de(), ["instalacao-fora-do-lockfile"])


class TestM1Renovate(ComArvore):
    def regras_de(self) -> list[str]:
        return self.regras(renovate.verificar(self.raiz)[0])

    def test_ficheiros_sombra(self) -> None:
        for nome in renovate.SOMBRAS + renovate.OUTROS_ACTUALIZADORES:
            with self.subTest(nome=nome):
                self.escrever(nome, '{"automerge": true, "minimumReleaseAge": null}\n')
                try:
                    self.assertEqual(self.regras_de(), ["configuracao-sombra"])
                finally:
                    (self.raiz / nome).unlink()

    def test_chave_renovate_no_package_json(self) -> None:
        self.escrever("package.json", '{"name": "x", "renovate": {"automerge": true}}\n')
        self.assertEqual(self.regras_de(), ["configuracao-sombra"])

    def test_automerge_e_quarentena_em_qualquer_profundidade(self) -> None:
        for trecho, esperado in (
            ('  extends: ["config:recommended", ":automergeAll"],\n', ["automerge-ligado"]),
            ('  extends: ["config:recommended", ":automergeMinor"],\n', ["automerge-ligado"]),
            ("  patch: { automerge: true },\n", ["automerge-ligado"]),
            ("  patch: { minimumReleaseAge: null },\n", ["quarentena-desligada"]),
            ('  npm: { minimumReleaseAge: "0 days" },\n', ["quarentena-desligada"]),
            ("  lockFileMaintenance: { automerge: true },\n", ["automerge-ligado"]),
            ("  platformAutomerge: true,\n", ["automerge-ligado"]),
            ('  pip_requirements: { packageRules: [{ matchPackageNames: ["x"], automerge: true }] },\n', ["automerge-ligado"]),
            ('  packageRules: [{ extends: [":automergePatch"] }],\n', ["automerge-ligado"]),
        ):
            with self.subTest(trecho=trecho):
                original = self.ler("renovate.json5")
                if trecho.lstrip().startswith(("extends", "packageRules")):
                    chave = trecho.strip().split(":", 1)[0]
                    texto = re.sub(rf"(?m)^  {chave}: \[[^\n]*\],\n|^  {chave}: \[\n(?:.*\n)*?  \],\n", trecho, original, count=1)
                    self.assertNotEqual(texto, original)
                    self.escrever("renovate.json5", texto)
                else:
                    self.trocar("renovate.json5", "  automerge: false,\n  packageRules", trecho + "  automerge: false,\n  packageRules")
                try:
                    self.assertEqual(self.regras_de(), esperado)
                finally:
                    self.escrever("renovate.json5", original)

    def test_automerge_na_excepcao_de_seguranca_mesmo_com_quarentena(self) -> None:
        self.trocar("renovate.json5", "    minimumReleaseAge: null,\n", "")
        self.trocar("renovate.json5", "    automerge: false,\n  },", "    automerge: true,\n  },")
        self.assertEqual(self.regras_de(), ["automerge-ligado"])


class TestM3M4eMenores(ComArvore):
    def test_m3_variantes_do_litellm(self) -> None:
        digest = "sha256:" + "a" * 64
        for nome, obrigatorio in (
            ("ghcr.io/berriai/litellm-database", True),
            ("ghcr.io/berriai/litellm-non_root", True),
            ("docker.io/litellm/litellm", True),
            ("litellm", True),
            ("exemplo/litellmx", False),
            ("exemplo/xlitellm", False),
        ):
            with self.subTest(nome=nome):
                original_i, original_c = self.ler(INVENTARIO), self.ler(COMPOSE)
                self.trocar(
                    INVENTARIO, "fontes_adicionais:",
                    f"  - nome: {nome}\n    etiqueta: v1\n    digest: \"{digest}\"\n"
                    "    lido_em: \"2026-10-12\"\n    lido_de: teste\n    componentes:\n      - node\n"
                    "    cosign: por_apurar\n"
                    "    cosign_razao: \"Uma razao com mais de quarenta caracteres, a fingir duvida.\"\n"
                    "fontes_adicionais:",
                )
                self.trocar(COMPOSE, f"image: pgvector/pgvector:0.8.7-pg18@{D_PG}", f"image: {nome}:v1@{digest}")
                try:
                    regras = self.regras(imagens.verificar(self.raiz)[0])
                finally:
                    self.escrever(INVENTARIO, original_i)
                    self.escrever(COMPOSE, original_c)
                self.assertEqual(regras, ["cosign-obrigatorio"] if obrigatorio else [])

    def test_m4_contexto_de_segredos_em_qualquer_forma(self) -> None:
        for linha in (
            "  TUDO: ${{ toJSON(secrets) }}",
            "  X: ${{ SECRETS.CHAVE }}",
            "  X: ${{ Secrets['CHAVE'] }}",
            "  X: ${{ format('{0}', secrets) }}",
            "    SECRETS: INHERIT",
        ):
            with self.subTest(linha=linha):
                original = self.ler(WORKFLOW)
                self.escrever(WORKFLOW, original + linha + "\n")
                try:
                    achados, _ = ci_chaves.verificar(self.raiz)
                finally:
                    self.escrever(WORKFLOW, original)
                self.assertEqual(self.regras(achados), ["chave-estatica-no-ci"])

    def test_m1_lancadores_noutras_formas(self) -> None:
        for ficheiro, linha in (
            ("ops/x.sh", "docker container run --rm litellm:latest\n"),
            ("ops/x.sh", "podman run --rm litellm:latest\n"),
            ("ops/x.sh", "nerdctl pull litellm:latest\n"),
            ("ops/tests/x.sh", "docker run --rm litellm:latest\n"),
            (".github/workflows/outro.yaml", "jobs:\n  a:\n    steps:\n      - run: docker run --rm litellm:latest\n"),
        ):
            with self.subTest(ficheiro=ficheiro, linha=linha[:30]):
                self.escrever(ficheiro, linha)
                try:
                    regras = self.regras(imagens.verificar(self.raiz)[0])
                finally:
                    (self.raiz / ficheiro).unlink()
                self.assertEqual(regras, ["lancador-nao-declarado"])

    def test_m2_egress_fora_de_services_e_ficheiro_ao_lado(self) -> None:
        self.escrever("apps/novo/Dockerfile", f"FROM node:24.21.0-trixie-slim@{D_NODE}\n")
        achados, _ = egress.verificar(self.raiz)
        self.assertEqual([(a.regra, a.ficheiro) for a in achados], [("egress-em-falta", "apps/novo/egress.yaml")])
        self.escrever("apps/novo/egress.yaml", "version: 1\nservico: novo\npor_omissao: negar\ndestinos: []\n")
        self.assertEqual(egress.verificar(self.raiz)[0], [])

        self.escrever("services/gwy/egress.yml", "version: 1\nservico: gwy\npor_omissao: permitir\ndestinos: []\n")
        achados, _ = egress.verificar(self.raiz)
        self.assertEqual([(a.regra, a.ficheiro) for a in achados], [("egress-orfao", "services/gwy/egress.yml")])

    def test_m3_digest_de_63_e_de_65_hexadecimais(self) -> None:
        for digest in ("sha256:" + "1" * 63, "sha256:" + "1" * 65, "sha256:" + "1" * 8):
            with self.subTest(tamanho=len(digest)):
                self.assertIsNone(imagens.decompor(f"node:24@{digest}"))
                original = self.ler(COMPOSE)
                self.trocar(COMPOSE, f"0.8.7-pg18@{D_PG}", f"0.8.7-pg18@{digest}")
                try:
                    self.assertEqual(self.regras(imagens.verificar(self.raiz)[0]), ["imagem-sem-digest"])
                finally:
                    self.escrever(COMPOSE, original)

    def test_m3_ficheiro_com_sufixo_env(self) -> None:
        self.escrever("infra/compose/prod.env", "FILA_IMAGEM=redis:8\n")
        achados, _ = imagens.verificar(self.raiz)
        self.assertEqual([(a.regra, a.ficheiro) for a in achados], [("imagem-sem-digest", "infra/compose/prod.env")])


class TestM6OGateCorre(unittest.TestCase):
    """O canario prova que as regras mordem; isto prova que o canario e chamado."""

    def setUp(self) -> None:
        self.texto = (ROOT / "Makefile").read_text(encoding="utf-8")

    def receita(self, alvo: str) -> str:
        correspondencia = re.search(rf"(?m)^{re.escape(alvo)}:[^\n]*\n((?:\t[^\n]*\n)+)", self.texto)
        self.assertIsNotNone(correspondencia, f"alvo {alvo} sem receita")
        return "\n".join(
            linha for linha in correspondencia.group(1).split("\n") if not linha.strip().startswith("@#")
        )

    def test_o_gate_11_chama_o_supply_chain(self) -> None:
        self.assertIn("$(MAKE) supply-chain", self.receita("ci-11"))

    def test_o_supply_chain_corre_o_check_e_o_canario(self) -> None:
        receita = self.receita("supply-chain")
        for passo in ("'check'", "'canario'"):
            with self.subTest(passo=passo):
                self.assertRegex(receita, rf"supply_chain\.cli import main.*{passo}")

    def test_o_workflow_corre_o_gate_11_e_ele_esta_no_resumo(self) -> None:
        workflow = (ROOT / ".github/workflows/ci.yaml").read_text(encoding="utf-8")
        self.assertIn("run: make ci-11", workflow)
        self.assertRegex(workflow, r"needs:(?:\n\s+- [\w-]+)*\n\s+- gate-11-supply-chain")
        self.assertNotRegex(workflow, r"gate-11-supply-chain:\n(?:.*\n){0,8}?\s+continue-on-error: true")


if __name__ == "__main__":
    unittest.main()
