"""Estrutura obrigatoria do monorepo, conforme o KAM-001.

A arvore e um contrato: os tickets seguintes assumem onde as coisas vivem
(`db/migrations` para o KAM-003, `registry/` para o AgentRegistry, `packages/contracts`
como fonte unica dos esquemas). Verificar que existe e mais barato do que descobrir
que alguem a mudou.
"""

from __future__ import annotations

from pathlib import Path

#: Servicos do Piloto (`docs/tecnica/09` §3.1). `com` e o anfitriao do Medusa 2.21.x;
#: a vitrine Next.js fica para Clusters e por isso nao esta aqui (ADR-019).
SERVICES = ("gwy", "worker-canal", "agr", "com", "onboarding-web")

#: Directorios de topo que o ticket fixa.
REQUIRED_DIRS = (
    "services",
    "packages/contracts",
    "packages/core-ts",
    "libs/py-core",
    "db/migrations",
    "registry",
    "infra",
    "tools",
)

#: Ficheiros de topo sem os quais a toolchain nao e reprodutivel.
REQUIRED_FILES = (
    "Makefile",
    "package.json",
    "pnpm-workspace.yaml",
    ".npmrc",
    ".node-version",
    "CODEOWNERS",
    "renovate.json5",
    "commitlint.config.cjs",
    "tools/blocklist.yaml",
    "tools/conventions.json",
    "infra/compose/docker-compose.dev.yml",
    "docs/evidencia/KAM-001-node.md",
    ".dockerignore",
    ".gitignore",
)

#: Cada servico tem estes tres. O `Dockerfile` e multi-stage; o digest fixo e KAM-067.
SERVICE_ENTRIES = ("src", "tests", "Dockerfile")

#: Ficheiros que nao podem existir, em nenhum sitio do repositorio.
#:
#: `ignore-scripts=true` no `.npmrc` impede os `postinstall` dos pacotes, mas a
#: documentacao do pnpm e explicita: **nao impede a execucao de `.pnpmfile`**. Um
#: `.pnpmfile` no repositorio seria, portanto, uma saida de emergencia do unico
#: controlo que protege o `pnpm install` (`docs/tecnica/08` §4.8). Se algum dia houver
#: razao para ter um, a razao entra num ADR e esta lista muda com ela.
FORBIDDEN_FILES = (
    ".pnpmfile.cjs",
    ".pnpmfile.mjs",
    ".pnpmfile.js",
)


#: Padroes que o `.dockerignore` tem obrigatoriamente de excluir.
#:
#: O `make bootstrap` cria `.env` na raiz, e a raiz e o contexto de build dos
#: servicos. Sem estas linhas, a senha do Postgres do desenvolvedor entra numa
#: camada de imagem e fica visivel em `docker history` — contra o DoD do KAM-001
#: ("sem segredos"), `docs/tecnica/08` §5 e o critério de saida do EPIC-01 ("0
#: segredos em camadas de imagem"). Uma linha apagada num `.dockerignore` nao da
#: erro em nenhum sitio; esta verificacao e esse erro.
REQUIRED_DOCKERIGNORE = (".env", ".env.*", "*.pem", "*.key")


def check(root: Path) -> list[str]:
    """Devolve a lista de desvios da estrutura. Lista vazia = conforme."""
    problems: list[str] = []

    dockerignore = root / ".dockerignore"
    if dockerignore.is_file():
        linhas = {
            line.strip()
            for line in dockerignore.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        }
        for padrao in REQUIRED_DOCKERIGNORE:
            if padrao not in linhas:
                problems.append(
                    f".dockerignore nao exclui {padrao!r}: um segredo do ambiente "
                    "local entraria numa camada de imagem (DoD do KAM-001, "
                    "docs/tecnica/08 §5)"
                )
    else:
        problems.append(
            ".dockerignore em falta: o contexto de build e a raiz do monorepo e "
            "inclui o .env (DoD do KAM-001)"
        )

    for relative in REQUIRED_DIRS:
        if not (root / relative).is_dir():
            problems.append(f"directorio obrigatorio em falta: {relative}/")

    for relative in REQUIRED_FILES:
        if not (root / relative).is_file():
            problems.append(f"ficheiro obrigatorio em falta: {relative}")

    for service in SERVICES:
        base = root / "services" / service
        if not base.is_dir():
            problems.append(f"servico em falta: services/{service}/")
            continue
        for entry in SERVICE_ENTRIES:
            if not (base / entry).exists():
                problems.append(f"services/{service}/{entry} em falta")

    for name in FORBIDDEN_FILES:
        for found in root.rglob(name):
            if "node_modules" in found.parts:
                continue
            problems.append(
                f"{found.relative_to(root).as_posix()} nao pode existir: o pnpm "
                "executa-o mesmo com `ignore-scripts=true`, o que anularia o "
                "controlo de cadeia de abastecimento (docs/tecnica/08 §4.8)"
            )

    # Um servico a mais e tao problematico como um a menos: significa que a
    # topologia mudou sem passar por `docs/tecnica/09` §3.1.
    if (root / "services").is_dir():
        found = {p.name for p in (root / "services").iterdir() if p.is_dir()}
        for extra in sorted(found - set(SERVICES)):
            problems.append(
                f"servico services/{extra}/ nao esta em docs/tecnica/09 §3.1; "
                "acrescentar um servico exige actualizar a topologia e esta lista"
            )

    return problems
