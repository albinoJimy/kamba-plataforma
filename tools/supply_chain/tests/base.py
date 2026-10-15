"""Arvores temporarias para os testes: um repositorio minimo, e conforme.

Cada teste parte de `MINIMO` — que passa todas as verificacoes — e estraga uma
coisa. Partir de uma arvore vazia provava pouco: quase tudo falha numa arvore
vazia, e um teste que espera um vermelho passava pela razao errada.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

D_PG = "sha256:" + "1" * 64
D_NODE = "sha256:" + "2" * 64
D_FILA = "sha256:" + "3" * 64

INVENTARIO = f"""version: 1
imagens:
  - nome: pgvector/pgvector
    etiqueta: 0.8.7-pg18
    digest: "{D_PG}"
    lido_em: "2026-10-12"
    lido_de: "teste"
    componentes:
      - postgresql
    cosign: por_apurar
    cosign_razao: "Nao se apurou se ha assinatura publicada; digest fixado."
  - nome: node
    etiqueta: 24.21.0-trixie-slim
    digest: "{D_NODE}"
    lido_em: "2026-10-12"
    lido_de: "teste"
    componentes:
      - node
    cosign: n/a
    cosign_razao: "Apurado que nao ha assinatura; compensa-se com digest, SBOM e varrimento."
  - nome: valkey/valkey
    etiqueta: 9.1.2-trixie
    digest: "{D_FILA}"
    lido_em: "2026-10-12"
    lido_de: "teste"
    componentes:
      - valkey
    cosign: por_apurar
    cosign_razao: "Nao se apurou se ha assinatura publicada; digest fixado."
fontes_adicionais:
  - ficheiro: db/gate.py
    constante: IMAGEM
"""

LICENCAS = """version: 1
componentes:
  - componente: postgresql
    versao: "18.6"
    licenca: PostgreSQL
    data_verificacao: "2026-10-08"
    fonte: "teste"
    estado_verificacao: CONFIRMADO
    estado: permitido
  - componente: node
    versao: "24.21.0"
    licenca: MIT
    data_verificacao: "2026-10-08"
    fonte: "teste"
    estado_verificacao: CONFIRMADO
    estado: permitido
    ligacoes:
      - "imagem:node"
  - componente: valkey
    versao: "9.1.2"
    licenca: BSD-3-Clause
    data_verificacao: "2026-10-08"
    fonte: "teste"
    estado_verificacao: INDÍCIO
    estado: pendente_de_decisao
    decisao: D12
    ligacoes:
      - "imagem:valkey/valkey"
  - componente: hono
    versao: "4.13.13"
    licenca: MIT
    data_verificacao: "2026-10-08"
    fonte: "teste"
    estado_verificacao: CONFIRMADO
    estado: permitido
    ligacoes:
      - "npm:hono"
  - componente: medusa
    versao: "2.21.2"
    licenca: MIT
    data_verificacao: "2026-10-08"
    fonte: "teste"
    estado_verificacao: CONFIRMADO
    estado: permitido
    ee: "RBAC e SSO/OIDC sao proprietarios e ficam desligados."
    ligacoes:
      - "npm:@medusajs/medusa"
  - componente: meilisearch
    versao: "1.54.3"
    licenca: MIT AND BUSL-1.1
    data_verificacao: "2026-10-08"
    fonte: "teste"
    estado_verificacao: CONFIRMADO
    estado: nao_adoptado
    ee: "Os modulos Enterprise Edition sao BUSL-1.1."
    ligacoes:
      - "npm:meilisearch"
  - componente: pgvector
    versao: "0.8.7"
    licenca: PostgreSQL
    data_verificacao: "2026-10-08"
    fonte: "teste"
    estado_verificacao: CONFIRMADO
    estado: permitido
  - componente: redis
    versao: "8.10.2"
    licenca: NOASSERTION
    data_verificacao: "2026-10-08"
    fonte: "teste"
    estado_verificacao: NÃO VERIFICADO
    estado: pendente_de_decisao
    decisao: D12
  - componente: chatwoot
    versao: "4.18.0"
    licenca: MIT
    data_verificacao: "2026-10-08"
    fonte: "teste"
    estado_verificacao: CONFIRMADO
    estado: permitido
    ee: "A pasta enterprise/ nao se carrega."
  - componente: litellm
    versao: "1.104.2"
    licenca: MIT
    data_verificacao: "2026-10-08"
    fonte: "teste"
    estado_verificacao: CONFIRMADO
    estado: permitido
    ee: "A pasta enterprise/ nao se usa."
  - componente: langfuse
    versao: "4.55.0"
    licenca: MIT
    data_verificacao: "2026-10-08"
    fonte: "teste"
    estado_verificacao: CONFIRMADO
    estado: nao_adoptado
    ee: "As pastas ee/ ficam de fora."
    ligacoes:
      - "imagem:langfuse"
  - componente: minio
    versao: "RELEASE.2025-10-15"
    licenca: AGPL-3.0
    data_verificacao: "2026-10-08"
    fonte: "teste"
    estado_verificacao: CONFIRMADO
    estado: bloqueado
"""

COMPOSE = f"""name: teste

x-defaults: &defaults
  restart: unless-stopped
  read_only: true
  networks:
    - app

services:
  postgres:
    image: pgvector/pgvector:0.8.7-pg18@{D_PG}
    read_only: true
    networks:
      - data

  queue:
    image: ${{FILA_IMAGEM:-valkey/valkey:9.1.2-trixie@{D_FILA}}}
    read_only: true
    command:
      - "--appendonly"
      - "yes"

  gwy:
    <<: *defaults
    build:
      context: ../..
      dockerfile: services/gwy/Dockerfile
      args:
        COMMIT: ${{COMMIT:-unknown}}
    healthcheck:
      test:
        - CMD
        - node
        - -e
        - >-
          fetch('http://127.0.0.1:3000/healthz')
          .then(r => process.exit(r.ok ? 0 : 1))

networks:
  app:
    driver: bridge
  data:
    internal: true
"""

DOCKERFILE = f"""# gwy
ARG NODE_IMAGE=node:24.21.0-trixie-slim@{D_NODE}

FROM ${{NODE_IMAGE}} AS deps
WORKDIR /app
RUN corepack enable
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile --ignore-scripts

FROM ${{NODE_IMAGE}} AS runtime
ARG COMMIT=unknown
COPY --from=deps /app ./
USER node
CMD ["node", "services/gwy/src/server.ts"]
"""

EGRESS = "version: 1\nservico: {nome}\npor_omissao: negar\ndestinos: []\n"

RENOVATE = """{
  // quarentena
  $schema: "https://docs.renovatebot.com/renovate-schema.json",
  extends: ["config:recommended"],
  minimumReleaseAge: "7 days",
  vulnerabilityAlerts: {
    minimumReleaseAge: null,
    enabled: true,
    labels: ["dependencias", "seguranca"],
    reviewers: ["team:plataforma"],
    automerge: false,
  },
  automerge: false,
  packageRules: [
    { matchPackageNames: ["hono"], allowedVersions: "<5.0.0" },
  ],
}
"""

WORKFLOW = """name: ci
on:
  pull_request:
    branches: [main]
permissions:
  contents: read
jobs:
  gate:
    runs-on: ubuntu-latest
    needs:
    - outro
    steps:
      - uses: actions/checkout@v5
      - name: correr
        run: |
          make ci-1
          echo "feito"
  outro:
    runs-on: ubuntu-latest
    steps:
      - run: make ci-2
"""

GATE_PY = f'''"""Lanca um contentor."""
import subprocess

IMAGEM = (
    "pgvector/pgvector:0.8.7-pg18"
    "@{D_PG}"
)


def correr():
    return subprocess.run(["docker", "run", "--rm", IMAGEM])
'''

PNPM_LOCK = """lockfileVersion: '9.0'

importers:

  services/gwy:
    dependencies:
      hono:
        specifier: 4.13.13
        version: 4.13.13

packages:

  hono@4.13.13:
    resolution: {integrity: sha512-x}

snapshots:

  hono@4.13.13: {}
"""

MINIMO = {
    "ci/supply-chain/imagens.yaml": INVENTARIO,
    "ci/supply-chain/licencas.yaml": LICENCAS,
    "infra/compose/docker-compose.dev.yml": COMPOSE,
    "services/gwy/Dockerfile": DOCKERFILE,
    "services/gwy/package.json": '{"name": "@kamba/gwy", "version": "0.1.0", "scripts": {"start": "node src/server.ts"}, "dependencies": {"hono": "4.13.13"}}\n',
    "services/gwy/egress.yaml": EGRESS.format(nome="gwy"),
    "infra/egress/postgres.yaml": EGRESS.format(nome="postgres"),
    "infra/egress/queue.yaml": EGRESS.format(nome="queue"),
    "renovate.json5": RENOVATE,
    ".github/workflows/ci.yaml": WORKFLOW,
    "db/gate.py": GATE_PY,
    "pnpm-lock.yaml": PNPM_LOCK,
    ".env.example": f"FILA_IMAGEM=valkey/valkey:9.1.2-trixie@{D_FILA}\nOUTRA=1\n",
    "Makefile": "bootstrap:\n\t@pnpm install --frozen-lockfile --ignore-scripts\n\t@echo \"pip install nada\"\n",
}


class ComArvore(unittest.TestCase):
    """Cada teste recebe em `self.raiz` uma copia de `MINIMO`, mais as politicas reais."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="kamba-sc-")
        self.addCleanup(self._tmp.cleanup)
        self.raiz = Path(self._tmp.name)
        for ficheiro, texto in MINIMO.items():
            self.escrever(ficheiro, texto)
        # As politicas vem do repositorio: o registo confronta-se com a
        # allowlist e com a lista de bloqueio verdadeiras, nao com copias.
        # ...e as duas fontes dos ADR, que a regra da excepcao le.
        for ficheiro in (
            "ci/licenses.yaml",
            "tools/blocklist.yaml",
            "docs/tecnica/00_Arquitectura_Solucao.md",
            "docs/adr/ADR-L001-toolchain.md",
        ):
            destino = self.raiz / ficheiro
            destino.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / ficheiro, destino)

    def escrever(self, ficheiro: str, texto: str) -> None:
        caminho = self.raiz / ficheiro
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_text(texto, encoding="utf-8", newline="\n")

    def ler(self, ficheiro: str) -> str:
        return (self.raiz / ficheiro).read_text(encoding="utf-8")

    def trocar(self, ficheiro: str, antigo: str, novo: str) -> None:
        texto = self.ler(ficheiro)
        self.assertIn(antigo, texto, f"{ficheiro} nao tem {antigo!r}: o teste nao estraga nada")
        self.escrever(ficheiro, texto.replace(antigo, novo, 1))

    def regras(self, achados) -> list[str]:
        return sorted(achado.regra for achado in achados)
