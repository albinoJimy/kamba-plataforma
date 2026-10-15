"""Imagens por digest e inventario (KAM-067, criterios 1 e 2)."""

from __future__ import annotations

import datetime
import unittest

from supply_chain import imagens
from supply_chain.base import ConfiguracaoInvalida
from supply_chain.imagens import decompor, nome_canonico

from .base import D_FILA, D_NODE, D_PG, ComArvore

COMPOSE = "infra/compose/docker-compose.dev.yml"
DOCKERFILE = "services/gwy/Dockerfile"
INVENTARIO = "ci/supply-chain/imagens.yaml"
OUTRO = "sha256:" + "9" * 64


class TestDecompor(unittest.TestCase):
    def test_formas_validas(self) -> None:
        for texto, esperado in (
            ("node", ("node", None, None)),
            ("node:24", ("node", "24", None)),
            (f"node:24@{D_NODE}", ("node", "24", D_NODE)),
            (f"node@{D_NODE}", ("node", None, D_NODE)),
            ("ghcr.io/berriai/litellm:main-v1.104.2", ("ghcr.io/berriai/litellm", "main-v1.104.2", None)),
            ("localhost:5000/x/y:1", ("localhost:5000/x/y", "1", None)),
            ("localhost:5000/x/y", ("localhost:5000/x/y", None, None)),
            ("Node:24", ("node", "24", None)),
        ):
            with self.subTest(texto=texto):
                partes = decompor(texto)
                self.assertIsNotNone(partes)
                self.assertEqual((partes.nome, partes.etiqueta, partes.digest), esperado)

    def test_digest_malformado_nao_conta_como_digest(self) -> None:
        for texto in (
            "node@sha256:abc",
            "node@sha256:" + "g" * 64,
            "node@sha256:" + "A" * 64,
            "node@md5:" + "1" * 32,
            "node:24@",
            "no de:1",
            "",
        ):
            with self.subTest(texto=texto):
                self.assertIsNone(decompor(texto))

    def test_nome_canonico(self) -> None:
        self.assertEqual(nome_canonico("docker.io/library/node"), "node")
        self.assertEqual(nome_canonico("library/node"), "node")
        self.assertEqual(nome_canonico("docker.io/pgvector/pgvector"), "pgvector/pgvector")
        self.assertEqual(nome_canonico("ghcr.io/x/node"), "ghcr.io/x/node")


class TestRepositorioMinimo(ComArvore):
    def test_o_minimo_passa(self) -> None:
        achados, resumo = imagens.verificar(self.raiz)
        self.assertEqual([str(a) for a in achados], [])
        # compose: postgres, queue; `.env.example`; Dockerfile (um `ARG`, usado
        # por dois `FROM`, conta uma vez); a constante de `db/gate.py`.
        self.assertEqual(resumo["referencias"], 5)
        self.assertEqual(resumo["cosign"], {"verificar": 0, "n/a": 1, "por_apurar": 2})

    # ---------------------------------------------------- sem digest

    def test_image_litellm_latest_e_o_caso_semeado_do_ticket(self) -> None:
        self.trocar(COMPOSE, f"image: pgvector/pgvector:0.8.7-pg18@{D_PG}", "image: litellm:latest")
        achados, _ = imagens.verificar(self.raiz)
        self.assertEqual(self.regras(achados), ["imagem-sem-digest"])
        self.assertEqual(achados[0].ficheiro, COMPOSE)
        self.assertIn("litellm:latest", achados[0].mensagem)

    def test_etiqueta_sem_digest_em_cada_sitio(self) -> None:
        for ficheiro, antigo, novo in (
            (COMPOSE, f"valkey/valkey:9.1.2-trixie@{D_FILA}}}", "valkey/valkey:9.1.2-trixie}"),
            (".env.example", f"@{D_FILA}", ""),
            ("db/gate.py", f'\n    "@{D_PG}"', ""),
        ):
            with self.subTest(ficheiro=ficheiro):
                original = self.ler(ficheiro)
                self.trocar(ficheiro, antigo, novo)
                try:
                    achados, _ = imagens.verificar(self.raiz)
                finally:
                    self.escrever(ficheiro, original)
                self.assertEqual(self.regras(achados), ["imagem-sem-digest"])
                self.assertEqual(achados[0].ficheiro, ficheiro)

    def test_etiqueta_sem_digest_no_dockerfile(self) -> None:
        """Um `ARG` usado por dois `FROM` da **um** achado, na linha do `ARG`.

        E a unica referencia ao Node neste repositorio minimo, pelo que a
        entrada do inventario fica tambem sem uso — e isso e um segundo achado
        legitimo, nao ruido.
        """
        self.trocar(DOCKERFILE, f"@{D_NODE}", "")
        achados, _ = imagens.verificar(self.raiz)
        self.assertEqual(self.regras(achados), ["imagem-sem-digest", "inventario-entrada-morta"])
        self.assertEqual((achados[0].ficheiro, achados[0].linha), (DOCKERFILE, 2))
        self.assertIn("ARG NODE_IMAGE", achados[0].mensagem)

    def test_digest_curto_ou_noutro_algoritmo(self) -> None:
        for mau in ("@sha256:abc", "@sha256:" + "z" * 64, "@sha512:" + "1" * 128):
            with self.subTest(mau=mau):
                original = self.ler(COMPOSE)
                self.trocar(COMPOSE, f"0.8.7-pg18@{D_PG}", f"0.8.7-pg18{mau}")
                achados, _ = imagens.verificar(self.raiz)
                self.assertEqual(self.regras(achados), ["imagem-sem-digest"])
                self.escrever(COMPOSE, original)

    def test_aspas_e_comentario_na_linha_nao_escondem_a_etiqueta(self) -> None:
        self.trocar(
            COMPOSE, f"image: pgvector/pgvector:0.8.7-pg18@{D_PG}",
            f'image: "pgvector/pgvector:0.8.7-pg18"  # @{D_PG}',
        )
        achados, _ = imagens.verificar(self.raiz)
        self.assertEqual(self.regras(achados), ["imagem-sem-digest"])

    # --------------------------------------------- fora do inventario

    def test_digest_que_o_inventario_nao_conhece(self) -> None:
        self.trocar(COMPOSE, f"0.8.7-pg18@{D_PG}", f"0.8.7-pg18@{OUTRO}")
        achados, _ = imagens.verificar(self.raiz)
        self.assertEqual(self.regras(achados), ["imagem-fora-do-inventario"])

    def test_digest_de_outra_imagem_do_inventario(self) -> None:
        """Um digest registado, mas para outro nome, nao serve."""
        self.trocar(COMPOSE, f"0.8.7-pg18@{D_PG}", f"0.8.7-pg18@{D_NODE}")
        achados, _ = imagens.verificar(self.raiz)
        self.assertEqual(self.regras(achados), ["imagem-fora-do-inventario"])

    def test_etiqueta_diferente_da_registada_para_o_digest(self) -> None:
        self.trocar(COMPOSE, f"pgvector:0.8.7-pg18@{D_PG}", f"pgvector:0.9.0-pg18@{D_PG}")
        achados, _ = imagens.verificar(self.raiz)
        self.assertEqual(self.regras(achados), ["imagem-fora-do-inventario"])
        self.assertIn("etiqueta", achados[0].mensagem)

    def test_so_digest_sem_etiqueta_passa(self) -> None:
        self.trocar(COMPOSE, f"pgvector:0.8.7-pg18@{D_PG}", f"pgvector@{D_PG}")
        self.assertEqual(imagens.verificar(self.raiz)[0], [])

    def test_o_registo_explicito_e_a_mesma_imagem(self) -> None:
        self.trocar(COMPOSE, "image: pgvector/pgvector", "image: docker.io/pgvector/pgvector")
        self.trocar(DOCKERFILE, "ARG NODE_IMAGE=node:", "ARG NODE_IMAGE=docker.io/library/node:")
        self.assertEqual(imagens.verificar(self.raiz)[0], [])

    def test_entrada_morta(self) -> None:
        self.trocar(DOCKERFILE, f"ARG NODE_IMAGE=node:24.21.0-trixie-slim@{D_NODE}", "ARG OUTRA=1")
        self.trocar(DOCKERFILE, "FROM ${NODE_IMAGE} AS deps", "FROM scratch AS deps")
        self.trocar(DOCKERFILE, "FROM ${NODE_IMAGE} AS runtime", "FROM deps AS runtime")
        achados, _ = imagens.verificar(self.raiz)
        self.assertEqual(self.regras(achados), ["inventario-entrada-morta"])
        self.assertIn("node", achados[0].mensagem)

    # ------------------------------------------------- nao resolvida

    def test_variavel_sem_omissao(self) -> None:
        for forma in ("${FILA_IMAGEM}", "$FILA_IMAGEM", "${FILA_IMAGEM:?defina}", "valkey/valkey:${ETIQUETA}"):
            with self.subTest(forma=forma):
                original = self.ler(COMPOSE)
                self.trocar(COMPOSE, f"${{FILA_IMAGEM:-valkey/valkey:9.1.2-trixie@{D_FILA}}}", forma)
                achados, _ = imagens.verificar(self.raiz)
                self.assertIn("imagem-nao-resolvida", self.regras(achados))
                self.escrever(COMPOSE, original)

    def test_o_env_substitui_a_omissao_e_por_isso_conta(self) -> None:
        self.trocar(".env.example", f"FILA_IMAGEM=valkey/valkey:9.1.2-trixie@{D_FILA}", "FILA_IMAGEM=redis:8")
        achados, _ = imagens.verificar(self.raiz)
        self.assertEqual(self.regras(achados), ["imagem-sem-digest"])
        self.assertEqual((achados[0].ficheiro, achados[0].linha), (".env.example", 1))

    def test_o_env_local_tambem_conta_e_os_comentarios_nao(self) -> None:
        self.escrever(".env", "# FILA_IMAGEM=redis:8\nexport FILA_IMAGEM='redis:8'\nFILA_IMAGEM=\n")
        achados, _ = imagens.verificar(self.raiz)
        self.assertEqual([(a.regra, a.ficheiro, a.linha) for a in achados], [("imagem-sem-digest", ".env", 2)])

    def test_servico_sem_image_nem_build(self) -> None:
        self.trocar(COMPOSE, f"    image: pgvector/pgvector:0.8.7-pg18@{D_PG}\n", "")
        achados, _ = imagens.verificar(self.raiz)
        self.assertIn("imagem-nao-resolvida", self.regras(achados))

    def test_build_que_aponta_para_dockerfile_inexistente(self) -> None:
        self.trocar(COMPOSE, "dockerfile: services/gwy/Dockerfile", "dockerfile: services/nada/Dockerfile")
        achados, _ = imagens.verificar(self.raiz)
        self.assertEqual(self.regras(achados), ["imagem-nao-resolvida"])

    def test_compose_ilegivel_e_achado(self) -> None:
        self.trocar(COMPOSE, "    <<: *defaults", "    <<: *nao_existe")
        achados, _ = imagens.verificar(self.raiz)
        self.assertIn("ficheiro-ilegivel", self.regras(achados))

    # ------------------------------------------------------ Dockerfile

    def test_build_args_do_compose_que_trocam_a_base(self) -> None:
        self.trocar(COMPOSE, "        COMMIT: ${COMMIT:-unknown}", "        COMMIT: x\n        NODE_IMAGE: node:25")
        achados, _ = imagens.verificar(self.raiz)
        self.assertEqual(self.regras(achados), ["imagem-sem-digest"])
        self.assertIn("build.args.NODE_IMAGE", achados[0].mensagem)

    def test_build_args_em_lista(self) -> None:
        self.trocar(COMPOSE, "        COMMIT: ${COMMIT:-unknown}", "        - COMMIT=x\n        - NODE_IMAGE=node:25")
        achados, _ = imagens.verificar(self.raiz)
        self.assertEqual(self.regras(achados), ["imagem-sem-digest"])

    def test_um_arg_que_nao_alimenta_um_from_nao_e_imagem(self) -> None:
        self.trocar(COMPOSE, "        COMMIT: ${COMMIT:-unknown}", "        COMMIT: node:25")
        self.assertEqual(imagens.verificar(self.raiz)[0], [])

    def test_from_directo_com_flag_de_plataforma(self) -> None:
        self.trocar(DOCKERFILE, "FROM ${NODE_IMAGE} AS runtime", "FROM --platform=linux/amd64 minio/minio:latest AS runtime")
        achados, _ = imagens.verificar(self.raiz)
        self.assertEqual(self.regras(achados), ["imagem-sem-digest"])
        self.assertIn("minio/minio:latest", achados[0].mensagem)

    def test_from_com_arg_sem_omissao(self) -> None:
        self.trocar(DOCKERFILE, f"ARG NODE_IMAGE=node:24.21.0-trixie-slim@{D_NODE}", "ARG NODE_IMAGE")
        achados, _ = imagens.verificar(self.raiz)
        self.assertIn("imagem-nao-resolvida", self.regras(achados))

    def test_copy_from_de_imagem_externa(self) -> None:
        self.trocar(DOCKERFILE, "COPY --from=deps /app ./", "COPY --from=deps /app ./\nCOPY --from=busybox:1.37 /bin/sh /bin/sh")
        achados, _ = imagens.verificar(self.raiz)
        self.assertEqual(self.regras(achados), ["imagem-sem-digest"])

    def test_copy_from_de_andar_por_nome_e_por_indice_nao_e_imagem(self) -> None:
        self.trocar(DOCKERFILE, "COPY --from=deps /app ./", "COPY --from=deps /app ./\nCOPY --from=0 /app /copia")
        self.assertEqual(imagens.verificar(self.raiz)[0], [])

    def test_mount_from_de_imagem_externa(self) -> None:
        self.trocar(
            DOCKERFILE, "RUN corepack enable",
            "RUN --mount=type=bind,from=alpine:3,target=/x corepack enable",
        )
        achados, _ = imagens.verificar(self.raiz)
        self.assertEqual(self.regras(achados), ["imagem-sem-digest"])

    def test_directiva_syntax(self) -> None:
        self.escrever(DOCKERFILE, "# syntax=docker/dockerfile:1\n" + self.ler(DOCKERFILE))
        achados, _ = imagens.verificar(self.raiz)
        self.assertEqual(self.regras(achados), ["imagem-sem-digest"])
        self.assertEqual(achados[0].linha, 1)

    def test_from_em_varias_linhas(self) -> None:
        self.trocar(DOCKERFILE, "FROM ${NODE_IMAGE} AS runtime", "FROM \\\n  node:25 \\\n  AS runtime")
        achados, _ = imagens.verificar(self.raiz)
        self.assertEqual(self.regras(achados), ["imagem-sem-digest"])

    def test_dockerfile_com_outro_nome(self) -> None:
        for nome in ("Dockerfile.dev", "dev.Dockerfile", "Containerfile", "build/Dockerfile"):
            with self.subTest(nome=nome):
                self.escrever(f"services/gwy/{nome}", "FROM node:25\n")
                achados, _ = imagens.verificar(self.raiz)
                self.assertEqual(self.regras(achados), ["imagem-sem-digest"])
                (self.raiz / "services/gwy" / nome).unlink()

    # -------------------------------------------------------- GitHub

    def test_workflow_container_services_e_docker_uses(self) -> None:
        for trecho in (
            "    container: node:24\n",
            "    container:\n      image: node:24\n",
            "    services:\n      pg:\n        image: postgres:18\n",
        ):
            with self.subTest(trecho=trecho):
                original = self.ler(".github/workflows/ci.yaml")
                self.trocar(".github/workflows/ci.yaml", "  outro:\n", "  outro:\n" + trecho)
                achados, _ = imagens.verificar(self.raiz)
                self.assertEqual(self.regras(achados), ["imagem-sem-digest"])
                self.escrever(".github/workflows/ci.yaml", original)

    def test_uses_docker(self) -> None:
        self.trocar(".github/workflows/ci.yaml", "      - run: make ci-2", "      - uses: docker://alpine:3")
        achados, _ = imagens.verificar(self.raiz)
        self.assertEqual(self.regras(achados), ["imagem-sem-digest"])

    def test_imagem_por_expressao_do_github_nao_se_resolve(self) -> None:
        self.trocar(".github/workflows/ci.yaml", "  outro:\n", "  outro:\n    container: ${{ matrix.imagem }}\n")
        achados, _ = imagens.verificar(self.raiz)
        self.assertEqual(self.regras(achados), ["imagem-nao-resolvida"])

    def test_accao_composta_tambem_e_lida(self) -> None:
        self.escrever(
            ".github/actions/x/action.yaml",
            "name: x\nruns:\n  using: docker\n  image: docker://alpine:3\n",
        )
        achados, _ = imagens.verificar(self.raiz)
        self.assertEqual(self.regras(achados), ["imagem-sem-digest"])

    def test_workflow_ilegivel_e_achado(self) -> None:
        self.escrever(".github/workflows/mau.yaml", "a:\n\tb: 1\n")
        achados, _ = imagens.verificar(self.raiz)
        self.assertEqual(self.regras(achados), ["ficheiro-ilegivel"])

    # ----------------------------------------------------- lancadores

    def test_python_que_chama_o_docker_sem_estar_declarado(self) -> None:
        self.escrever("tools/novo.py", 'import subprocess\nsubprocess.run(["docker", "run", "alpine:3"])\n')
        achados, _ = imagens.verificar(self.raiz)
        self.assertEqual(self.regras(achados), ["lancador-nao-declarado"])
        self.assertEqual(achados[0].ficheiro, "tools/novo.py")

    def test_python_declarado_sem_imagem(self) -> None:
        self.escrever("tools/novo.py", 'import subprocess\nsubprocess.run(["docker", "ps"])\n')
        self.escrever(
            INVENTARIO,
            self.ler(INVENTARIO)
            + "  - ficheiro: tools/novo.py\n    sem_imagem: \"So lista contentores; nao lanca nem descarrega imagem nenhuma.\"\n",
        )
        self.assertEqual(imagens.verificar(self.raiz)[0], [])

    def test_constante_em_falta_ou_que_nao_e_literal(self) -> None:
        for corpo in ("OUTRA = 'x'\n", "import os\nIMAGEM = os.environ['X']\n", "isto nao e python (\n"):
            with self.subTest(corpo=corpo):
                original = self.ler("db/gate.py")
                self.escrever("db/gate.py", corpo + 'import subprocess\nsubprocess.run(["docker", "run"])\n')
                achados, _ = imagens.verificar(self.raiz)
                self.assertIn("imagem-nao-resolvida", self.regras(achados))
                self.escrever("db/gate.py", original)

    def test_fonte_declarada_que_nao_existe(self) -> None:
        (self.raiz / "db/gate.py").unlink()
        achados, _ = imagens.verificar(self.raiz)
        self.assertEqual(self.regras(achados), ["inventario-entrada-morta"])

    def test_docker_run_num_script_ou_no_makefile(self) -> None:
        for ficheiro, linha in (
            ("ops/correr.sh", "docker run --rm alpine:3 true\n"),
            ("Makefile", "x:\n\t@docker pull redis:8\n"),
            ("ops/correr.sh", f"docker run --rm alpine@{OUTRO} true\n"),
        ):
            with self.subTest(ficheiro=ficheiro, linha=linha):
                original = self.ler(ficheiro) if (self.raiz / ficheiro).is_file() else None
                self.escrever(ficheiro, linha)
                achados, _ = imagens.verificar(self.raiz)
                self.assertEqual(self.regras(achados), ["lancador-nao-declarado"])
                if original is None:
                    (self.raiz / ficheiro).unlink()
                else:
                    self.escrever(ficheiro, original)

    def test_docker_run_com_digest_do_inventario_passa(self) -> None:
        self.escrever("ops/correr.sh", f"#!/bin/sh\n# docker run alpine:3\ndocker run --rm node@{D_NODE} node -v\n")
        self.assertEqual(imagens.verificar(self.raiz)[0], [])

    def test_os_testes_e_o_proprio_verificador_ficam_de_fora(self) -> None:
        self.escrever("tools/x/tests/test_a.py", 'CMD = ["docker", "run", "alpine:3"]\n')
        self.escrever("tools/supply_chain/y.py", 'CMD = ["docker", "run", "alpine:3"]\n')
        self.assertEqual(imagens.verificar(self.raiz)[0], [])

    # --------------------------------------------------------- cosign

    def test_litellm_nao_pode_ser_na_nem_por_apurar(self) -> None:
        digest = "sha256:" + "a" * 64
        for estado in ("n/a", "por_apurar"):
            with self.subTest(estado=estado):
                original_inventario, original_compose = self.ler(INVENTARIO), self.ler(COMPOSE)
                self.trocar(
                    INVENTARIO, "fontes_adicionais:",
                    "  - nome: ghcr.io/berriai/litellm\n    etiqueta: main-v1.104.2\n"
                    f"    digest: \"{digest}\"\n    lido_em: \"2026-10-12\"\n    lido_de: teste\n"
                    "    componentes:\n      - node\n"
                    f"    cosign: {estado}\n"
                    "    cosign_razao: \"Uma razao com mais de quarenta caracteres, a fingir compensacao.\"\n"
                    "fontes_adicionais:",
                )
                self.trocar(
                    COMPOSE, f"image: pgvector/pgvector:0.8.7-pg18@{D_PG}",
                    f"image: ghcr.io/berriai/litellm:main-v1.104.2@{digest}",
                )
                achados, _ = imagens.verificar(self.raiz)
                self.assertEqual(self.regras(achados), ["cosign-obrigatorio"])
                self.escrever(INVENTARIO, original_inventario)
                self.escrever(COMPOSE, original_compose)


class TestInventarioInvalido(ComArvore):
    """Erros de configuracao levantam: nunca degradam para «sem imagens»."""

    def invalido(self, antigo: str, novo: str, fragmento: str) -> None:
        self.trocar(INVENTARIO, antigo, novo)
        with self.assertRaises(ConfiguracaoInvalida) as contexto:
            imagens.verificar(self.raiz)
        self.assertIn(fragmento, str(contexto.exception))

    def test_ficheiro_em_falta(self) -> None:
        (self.raiz / INVENTARIO).unlink()
        with self.assertRaises(ConfiguracaoInvalida):
            imagens.verificar(self.raiz)

    def test_yaml_ilegivel(self) -> None:
        self.escrever(INVENTARIO, "version: 1\nimagens: [a, b]\n")
        with self.assertRaises(ConfiguracaoInvalida):
            imagens.verificar(self.raiz)

    def test_versao(self) -> None:
        self.invalido("version: 1", "version: 2", "'version' tem de ser 1")

    def test_imagens_tem_de_ser_lista(self) -> None:
        self.escrever(INVENTARIO, "version: 1\nfontes_adicionais: []\n")
        with self.assertRaises(ConfiguracaoInvalida):
            imagens.verificar(self.raiz)

    def test_chave_desconhecida_no_topo_e_na_entrada(self) -> None:
        self.invalido("version: 1", "version: 1\nexcepcoes: []", "nenhum codigo le")

    def test_chave_desconhecida_na_entrada(self) -> None:
        self.invalido("    cosign: n/a", "    cosign: n/a\n    ignorar: sim", "nenhum codigo le")

    def test_campo_em_falta(self) -> None:
        self.invalido('    lido_de: "teste"\n', "", "campos em falta: lido_de")

    def test_digest_malformado(self) -> None:
        self.invalido(D_PG, "sha256:abc", "64 hexadecimais")

    def test_data_futura_e_data_ilegivel(self) -> None:
        with self.assertRaises(ConfiguracaoInvalida) as contexto:
            imagens.ler_inventario(self.raiz, hoje=datetime.date(2026, 10, 11))
        self.assertIn("futuro", str(contexto.exception))
        self.invalido('lido_em: "2026-10-12"', 'lido_em: "ontem"', "data ISO")

    def test_estado_de_cosign_desconhecido(self) -> None:
        self.invalido("    cosign: n/a", "    cosign: dispensado", "`cosign` tem de ser um de")

    def test_na_e_por_apurar_exigem_razao(self) -> None:
        self.invalido(
            '    cosign_razao: "Apurado que nao ha assinatura; compensa-se com digest, SBOM e varrimento."\n',
            '    cosign_razao: "n/a"\n', "40",
        )

    def test_verificar_exige_identidade_e_emissor(self) -> None:
        self.invalido("    cosign: n/a", "    cosign: verificar", "cosign_identidade")

    def test_entrada_repetida(self) -> None:
        self.invalido(
            "fontes_adicionais:",
            f"  - nome: docker.io/library/node\n    etiqueta: outra\n    digest: \"{D_NODE}\"\n"
            "    lido_em: \"2026-10-12\"\n    lido_de: teste\n    componentes:\n      - node\n"
            "    cosign: por_apurar\n    cosign_razao: \"Uma razao com mais de quarenta caracteres aqui.\"\n"
            "fontes_adicionais:",
            "repetida",
        )

    def test_fonte_adicional_exige_exactamente_um_de_constante_e_sem_imagem(self) -> None:
        self.invalido("    constante: IMAGEM\n", "", "exige `ficheiro`")

    def test_fonte_adicional_repetida(self) -> None:
        self.escrever(INVENTARIO, self.ler(INVENTARIO) + "  - ficheiro: db/gate.py\n    constante: OUTRA\n")
        with self.assertRaises(ConfiguracaoInvalida):
            imagens.verificar(self.raiz)

    def test_nome_e_etiqueta_invalidos(self) -> None:
        self.invalido("  - nome: node\n", "  - nome: Node Oficial\n", "nome de imagem invalido")


if __name__ == "__main__":
    unittest.main()
