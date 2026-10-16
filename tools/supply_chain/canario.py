"""O canario: cada verificacao falha perante o defeito, e prova-o **no gate**.

Um lint que passa nao diz se morde. A prova habitual vive num `unittest` com
*fixtures*, e este repositorio ja pagou duas vezes por isso: o gate 9 esteve
sete PRs sem nada que o provasse, e o primeiro canario do gate 3b dava verde com
a lista de casos vazia (`docs/ci.md` §3).

Aqui a prova e por **mutacao do proprio repositorio**: copia-se a arvore para
fora, confirma-se que a copia esta conforme (linha de base), e aplica-se um
defeito de cada vez — retirar um digest, pôr `image: litellm:latest`, ligar o
`automerge`. Cada mutacao tem de:

1. **aplicar-se** — o texto que ela troca tem de existir. Uma mutacao que deixou
   de se aplicar porque o ficheiro mudou e uma prova que deixou de existir, e
   falha o canario em vez de passar calada;
2. dar vermelho **pelas regras esperadas, e so por essas** — ser apanhada por
   outra regra qualquer e sorte, nao cobertura.

A lista de mutacoes e codigo, nao configuracao: nao ha ficheiro que alguem
possa esvaziar para o canario passar. `MINIMO_POR_REGRA` prende, alem disso, as
regras que tem de continuar a ter pelo menos uma mutacao.
"""

from __future__ import annotations

import dataclasses
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Callable

from .base import SALTAR_DIRECTORIOS

#: Fora da copia: o que nenhuma verificacao le, e que so a tornava lenta.
_FORA_DA_COPIA = SALTAR_DIRECTORIOS | {"docs", "specs", ".claude", "coverage", "sbom"}
#: ...excepto as duas fontes dos ADR, que a regra da excepcao de licenca le.
_DE_DOCS = ("docs/tecnica/00_Arquitectura_Solucao.md", "docs/adr")


class NaoSeAplica(RuntimeError):
    """A mutacao ja nao encontra o texto que ia trocar."""


class Copia:
    """A arvore copiada, com as alteracoes de uma mutacao por repor."""

    def __init__(self, raiz: Path) -> None:
        self.raiz = raiz
        self._originais: dict[Path, str | None] = {}

    def _guardar(self, caminho: Path) -> None:
        if caminho not in self._originais:
            self._originais[caminho] = (
                caminho.read_text(encoding="utf-8") if caminho.is_file() else None
            )

    def ler(self, ficheiro: str) -> str:
        caminho = self.raiz / ficheiro
        if not caminho.is_file():
            raise NaoSeAplica(f"{ficheiro} nao existe")
        return caminho.read_text(encoding="utf-8")

    def escrever(self, ficheiro: str, texto: str) -> None:
        caminho = self.raiz / ficheiro
        self._guardar(caminho)
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_text(texto, encoding="utf-8", newline="\n")

    def trocar(self, ficheiro: str, padrao: str, novo: str) -> None:
        """Troca a primeira ocorrencia de `padrao` (expressao regular)."""
        texto = self.ler(ficheiro)
        resultado, quantas = re.subn(padrao, lambda _m: novo, texto, count=1, flags=re.MULTILINE)
        if quantas != 1 or resultado == texto:
            raise NaoSeAplica(f"{ficheiro}: nada bate em /{padrao}/")
        self.escrever(ficheiro, resultado)

    def acrescentar(self, ficheiro: str, texto: str) -> None:
        self.escrever(ficheiro, self.ler(ficheiro).rstrip("\n") + "\n" + texto)

    def apagar(self, ficheiro: str) -> None:
        caminho = self.raiz / ficheiro
        if not caminho.is_file():
            raise NaoSeAplica(f"{ficheiro} nao existe")
        self._guardar(caminho)
        caminho.unlink()

    def repor(self) -> None:
        for caminho, original in self._originais.items():
            if original is None:
                caminho.unlink(missing_ok=True)
            else:
                caminho.write_text(original, encoding="utf-8", newline="\n")
        self._originais.clear()


@dataclasses.dataclass(frozen=True)
class Mutacao:
    nome: str
    descricao: str
    #: As regras que tem de disparar — todas, e nenhuma outra.
    regras: frozenset[str]
    aplicar: Callable[[Copia], None]


_COMPOSE = "infra/compose/docker-compose.dev.yml"
_DIGEST = r"@sha256:[0-9a-f]{64}"
_INVENTARIO = "ci/supply-chain/imagens.yaml"
_LICENCAS = "ci/supply-chain/licencas.yaml"
_WORKFLOW = ".github/workflows/ci.yaml"
# O bloco inteiro, e nao so a primeira entrada: desde o KAM-011 ha mais dois
# lancadores declarados (`infra/storage/`), e tirar so o do gate deixava os
# outros pendurados num YAML invalido.
_FONTE_DO_GATE = r"^fontes_adicionais:\n(?:  .*\n)+"
_ESTADO_DO_VALKEY = (
    r'^    estado: pendente_de_decisao\n    decisao: D12\n    ligacoes:\n      - "imagem:valkey/valkey"$'
)
_ESTADO_DO_MEILISEARCH = r'^    estado: nao_adoptado\n    ligacoes:\n      - "npm:meilisearch"$'
# Um componente `permitido` que **nao esta** no repositorio: o BullMQ. Era o
# SeaweedFS ate o KAM-011 trazer a imagem de teste dele — com a imagem
# presente, marca-lo `bloqueado` dava dois achados em vez de um.
_ESTADO_DO_BULLMQ = r'^    estado: permitido\n    ligacoes:\n      - "npm:bullmq"$'


def _litellm_latest(copia: Copia) -> None:
    copia.trocar(_COMPOSE, r"image: pgvector/pgvector:[^\s]+", "image: litellm:latest")


def _litellm_sem_cosign(copia: Copia) -> None:
    copia.trocar(
        _INVENTARIO,
        r"^fontes_adicionais:",
        "  - nome: ghcr.io/berriai/litellm\n"
        "    etiqueta: main-v1.104.2\n"
        f"    digest: \"sha256:{'ab' * 32}\"\n"
        "    lido_em: \"2026-10-12\"\n"
        "    lido_de: \"mutacao do canario\"\n"
        "    componentes:\n"
        "      - litellm\n"
        "    cosign: n/a\n"
        "    cosign_razao: >-\n"
        "      Mutacao do canario: uma imagem com assinatura publicada registada como n/a.\n"
        "\nfontes_adicionais:",
    )
    copia.trocar(
        _COMPOSE,
        r"^  # -+ servicos\n",
        "  llm:\n"
        f"    image: ghcr.io/berriai/litellm:main-v1.104.2@sha256:{'ab' * 32}\n"
        "    read_only: true\n"
        "    networks:\n"
        "      - app\n\n"
        "  # ---- servicos\n",
    )
    copia.escrever(
        "infra/egress/llm.yaml",
        "version: 1\nservico: llm\npor_omissao: negar\ndestinos: []\n",
    )


def _destino_sem_nome(copia: Copia) -> None:
    copia.trocar(
        "services/agr/egress.yaml",
        r"^destinos: \[\]$",
        "destinos:\n"
        "  - fqdn: \"*\"\n"
        "    porta: 443\n"
        "    protocolo: https\n"
        "    razao: mutacao do canario, saida para qualquer lado\n"
        "    ticket: KAM-067",
    )


def _meilisearch_entra(copia: Copia) -> None:
    copia.trocar(
        "services/com/package.json",
        r'"dependencies": \{',
        '"dependencies": {\n    "meilisearch": "0.50.0",',
    )


MUTACOES: tuple[Mutacao, ...] = (
    # ------------------------------------------------------------- imagens
    Mutacao(
        "imagem-litellm-latest",
        "o caso semeado do criterio 1: `image: litellm:latest` no compose",
        frozenset({"imagem-sem-digest"}),
        _litellm_latest,
    ),
    Mutacao(
        "digest-retirado-da-omissao-do-compose",
        "a omissao de `KAMBA_QUEUE_IMAGE` volta a ser so a etiqueta",
        frozenset({"imagem-sem-digest"}),
        lambda c: c.trocar(_COMPOSE, r"(?<=valkey/valkey:9\.1\.2-trixie)" + _DIGEST, ""),
    ),
    Mutacao(
        "digest-retirado-do-env",
        "o `.env.example`, que substitui a omissao do compose, perde o digest",
        frozenset({"imagem-sem-digest"}),
        lambda c: c.trocar(".env.example", r"(?<=^KAMBA_QUEUE_IMAGE=valkey/valkey:9\.1\.2-trixie)" + _DIGEST, ""),
    ),
    Mutacao(
        "digest-retirado-do-dockerfile",
        "o `ARG NODE_IMAGE` de um Dockerfile volta a ser so a etiqueta",
        frozenset({"imagem-sem-digest"}),
        lambda c: c.trocar("services/gwy/Dockerfile", r"(?<=^ARG NODE_IMAGE=node:24\.21\.0-trixie-slim)" + _DIGEST, ""),
    ),
    Mutacao(
        "digest-retirado-do-gate-de-bd",
        "a constante `IMAGEM` de `db/gate_bd.py` perde o digest",
        frozenset({"imagem-sem-digest"}),
        lambda c: c.trocar("db/gate_bd.py", r'\n    "@sha256:[0-9a-f]{64}"', ""),
    ),
    Mutacao(
        "digest-que-ninguem-registou",
        "um digest bem formado que nao e o do inventario",
        frozenset({"imagem-fora-do-inventario"}),
        lambda c: c.trocar(_COMPOSE, r"(?<=image: pgvector/pgvector:0\.8\.7-pg18)" + _DIGEST, "@sha256:" + "0" * 64),
    ),
    Mutacao(
        "contentor-de-workflow-por-etiqueta",
        "um job do workflow passa a correr num `container:` sem digest",
        frozenset({"imagem-sem-digest"}),
        lambda c: c.trocar(_WORKFLOW, r"^  gate-9-segredos:\n", "  gate-9-segredos:\n    container: python:3.12\n"),
    ),
    Mutacao(
        "from-de-imagem-externa",
        "um `COPY --from=` que vai buscar ficheiros a uma imagem por etiqueta",
        frozenset({"imagem-sem-digest"}),
        lambda c: c.trocar("services/agr/Dockerfile", r"^USER nobody$", "COPY --from=busybox:1.37 /bin/busybox /bin/busybox\nUSER nobody"),
    ),
    Mutacao(
        "variavel-de-imagem-sem-omissao",
        "a imagem da fila passa a depender so do ambiente",
        frozenset({"imagem-nao-resolvida"}),
        lambda c: c.trocar(_COMPOSE, r"image: \$\{KAMBA_QUEUE_IMAGE:-[^}]+\}", "image: ${KAMBA_QUEUE_IMAGE}"),
    ),
    Mutacao(
        "lancador-retirado-do-inventario",
        "`db/gate_bd.py` chama o Docker e deixa de estar declarado",
        frozenset({"lancador-nao-declarado"}),
        lambda c: c.trocar(_INVENTARIO, _FONTE_DO_GATE, "fontes_adicionais: []\n"),
    ),
    Mutacao(
        "litellm-sem-cosign",
        "uma imagem do LiteLLM, por digest, registada com `cosign: n/a`",
        frozenset({"cosign-obrigatorio"}),
        _litellm_sem_cosign,
    ),
    # --- formas equivalentes que a revisao adversarial fez passar (ANALISE-10)
    Mutacao(
        "compose-em-estilo-de-fluxo",
        "um segundo compose, `services: {llm: {image: litellm:latest}}`",
        frozenset({"ficheiro-ilegivel"}),
        lambda c: c.escrever("infra/stack.yml", "services: {llm: {image: litellm:latest}}\n"),
    ),
    Mutacao(
        "compose-com-a-chave-entre-aspas",
        'um segundo compose com `"services":` entre aspas',
        frozenset({"imagem-sem-digest", "fs-so-de-leitura", "egress-em-falta"}),
        lambda c: c.escrever("infra/stack.yml", '"services":\n  llm:\n    image: litellm:latest\n'),
    ),
    Mutacao(
        "compose-em-json",
        "um `compose.json` com `image: litellm:latest`",
        frozenset({"ficheiro-ilegivel"}),
        lambda c: c.escrever("infra/compose.json", '{"services": {"llm": {"image": "litellm:latest"}}}\n'),
    ),
    Mutacao(
        "compose-com-bom",
        "um compose de producao com BOM no inicio e `image: litellm:latest`",
        frozenset({"imagem-sem-digest", "fs-so-de-leitura", "egress-em-falta"}),
        lambda c: c.escrever(
            "infra/compose/docker-compose.prod.yml",
            "\ufeffservices:\n  llm:\n    image: litellm:latest\n",
        ),
    ),
    Mutacao(
        "dockerfile-inline-no-compose",
        "um `build.dockerfile_inline` com `FROM litellm:latest`",
        frozenset({"imagem-nao-resolvida"}),
        lambda c: c.trocar(
            _COMPOSE, r"^      dockerfile: services/gwy/Dockerfile\n",
            "      dockerfile: services/gwy/Dockerfile\n      dockerfile_inline: FROM litellm:latest\n",
        ),
    ),
    Mutacao(
        "manifesto-de-kubernetes",
        "um manifesto com `image: minio/minio:latest` fora de qualquer compose",
        frozenset({"imagem-sem-digest"}),
        lambda c: c.escrever(
            "infra/k8s/armazenamento.yaml",
            "kind: Deployment\nspec:\n  containers:\n    - name: s3\n      image: minio/minio:latest\n",
        ),
    ),
    Mutacao(
        "dockerfile-com-outro-nome",
        "um `Dockerfile-base` com `FROM litellm:latest`",
        frozenset({"imagem-sem-digest", "egress-em-falta"}),
        lambda c: c.escrever("infra/imagens/Dockerfile-base", "FROM litellm:latest\n"),
    ),
    Mutacao(
        "heredoc-falso-esconde-o-resto",
        "um `RUN echo $((1<<n))` antes de um `FROM` sem digest e de um `CMD` que instala",
        frozenset({"imagem-sem-digest", "instalacao-em-runtime"}),
        lambda c: c.trocar(
            "services/agr/Dockerfile", r"^USER nobody$",
            'RUN echo $((1<<n))\nFROM python:3.12 AS segundo\nCMD ["sh", "-c", "pip install litellm"]\nUSER nobody',
        ),
    ),
    Mutacao(
        "heredoc-por-fechar",
        "um here-document que nunca fecha",
        frozenset({"ficheiro-ilegivel", "imagem-nao-resolvida", "inventario-entrada-morta"}),
        lambda c: c.trocar("services/agr/Dockerfile", r"^USER nobody$", "RUN <<FIM\necho x\nUSER nobody"),
    ),
    Mutacao(
        "litellm-database-sem-cosign",
        "`litellm-database`, do mesmo projecto, registada com `cosign: por_apurar`",
        frozenset({"cosign-obrigatorio", "inventario-entrada-morta"}),
        lambda c: c.trocar(
            _INVENTARIO, r"^fontes_adicionais:",
            "  - nome: ghcr.io/berriai/litellm-database\n    etiqueta: main-v1.104.2\n"
            f"    digest: \"sha256:{'cd' * 32}\"\n    lido_em: \"2026-10-12\"\n"
            "    lido_de: \"mutacao do canario\"\n    componentes:\n      - litellm\n"
            "    cosign: por_apurar\n    cosign_razao: >-\n"
            "      Mutacao do canario: variante do LiteLLM registada como por apurar.\n"
            "\nfontes_adicionais:",
        ),
    ),
    Mutacao(
        "inventario-com-entrada-morta",
        "uma imagem no inventario que nada referencia",
        frozenset({"inventario-entrada-morta"}),
        lambda c: c.trocar(
            _INVENTARIO, r"^fontes_adicionais:",
            "  - nome: busybox\n    etiqueta: \"1.37\"\n"
            f"    digest: \"sha256:{'ef' * 32}\"\n    lido_em: \"2026-10-12\"\n"
            "    lido_de: \"mutacao do canario\"\n    componentes:\n      - node\n"
            "    cosign: por_apurar\n    cosign_razao: >-\n"
            "      Mutacao do canario: um digest aprovado que ninguem usa.\n"
            "\nfontes_adicionais:",
        ),
    ),
    Mutacao(
        "docker-run-num-workflow",
        "um passo de workflow que faz `docker run` de uma imagem por etiqueta",
        frozenset({"lancador-nao-declarado"}),
        lambda c: c.trocar(_WORKFLOW, r"^        run: make ci-9$", "        run: docker container run --rm alpine:3 true"),
    ),
    # ------------------------------------------------------------- runtime
    Mutacao(
        "pip-com-opcao-global-no-arranque",
        "`pip --no-cache-dir install` no `CMD`: a opcao antes do subcomando",
        frozenset({"instalacao-em-runtime"}),
        lambda c: c.trocar("services/agr/Dockerfile", r'^CMD \["python", "-m", "kamba_agr"\]$', 'CMD ["sh", "-e", "-c", "/usr/local/bin/pip --no-cache-dir install litellm && python -m kamba_agr"]'),
    ),
    Mutacao(
        "npm-i-dentro-de-um-if-no-arranque",
        "`CMD if [ ! -d node_modules ]; then npm i; fi; node ...`",
        frozenset({"instalacao-em-runtime"}),
        lambda c: c.trocar("services/gwy/Dockerfile", r'^CMD \["node", "services/gwy/src/server.ts"\]$', "CMD if [ ! -d node_modules ]; then npm i; fi; node services/gwy/src/server.ts"),
    ),
    Mutacao(
        "script-de-arranque-que-chama-outro",
        "um `entrypoint` sem extensao que faz `. prepara.sh`, e este instala",
        frozenset({"instalacao-em-runtime"}),
        lambda c: (
            c.trocar("services/agr/Dockerfile", r'^CMD \["python", "-m", "kamba_agr"\]$', 'ENTRYPOINT ["/app/docker-entrypoint"]'),
            c.escrever("services/agr/docker-entrypoint", "#!/bin/sh\nset -e\n. /app/prepara.sh\nexec python -m kamba_agr\n"),
            c.escrever("services/agr/prepara.sh", "#!/bin/sh\ntimeout 300 python -u -m pip install litellm\n"),
        )[0],
    ),
    Mutacao(
        "script-de-arranque-que-nao-esta-no-repositorio",
        "um `CMD` que executa um ficheiro que nao se encontra",
        frozenset({"arranque-nao-verificavel"}),
        lambda c: c.trocar("services/agr/Dockerfile", r'^CMD \["python", "-m", "kamba_agr"\]$', 'CMD ["/opt/kamba/lanca.sh"]'),
    ),
    Mutacao(
        "arranque-por-script-do-package-json",
        "`CMD pnpm run arranque`, e `scripts.arranque` instala",
        frozenset({"instalacao-em-runtime"}),
        lambda c: (
            c.trocar("services/gwy/Dockerfile", r'^CMD \["node", "services/gwy/src/server.ts"\]$', 'CMD ["pnpm", "run", "arranque"]'),
            c.trocar("services/gwy/package.json", r'"scripts": \{', '"scripts": {\n    "arranque": "npm i && node src/server.ts",'),
        )[0],
    ),
    Mutacao(
        "pnpm-rebuild-depois-de-ignore-scripts",
        "`pnpm install ... --ignore-scripts && pnpm rebuild`",
        frozenset({"instalacao-fora-do-lockfile"}),
        lambda c: c.trocar("services/gwy/Dockerfile", r"pnpm install --frozen-lockfile --ignore-scripts", "pnpm install --frozen-lockfile --ignore-scripts && pnpm rebuild"),
    ),
    Mutacao(
        "pip-pelo-caminho-no-makefile",
        "`$(VENV)/bin/pip install --upgrade pip` no bootstrap",
        frozenset({"instalacao-fora-do-lockfile"}),
        lambda c: c.trocar("Makefile", r"^\t@\$\(PYTHON\) -m venv \$\(VENV\)\n", "\t@$(PYTHON) -m venv $(VENV)\n\t@$(VENV)/bin/pip install --quiet --upgrade pip\n"),
    ),
    Mutacao(
        "pip-install-no-arranque",
        "o `CMD` do AGR instala antes de arrancar",
        frozenset({"instalacao-em-runtime"}),
        lambda c: c.trocar("services/agr/Dockerfile", r'^CMD \["python", "-m", "kamba_agr"\]$', 'CMD ["sh", "-c", "pip install litellm && python -m kamba_agr"]'),
    ),
    Mutacao(
        "npm-i-no-entrypoint-do-compose",
        "um servico do compose ganha um `entrypoint` que corre `npm i`",
        frozenset({"instalacao-em-runtime"}),
        lambda c: c.trocar(_COMPOSE, r"^  gwy:\n", '  gwy:\n    entrypoint: ["sh", "-c", "npm i && node services/gwy/src/server.ts"]\n'),
    ),
    Mutacao(
        "pip-sem-hashes-na-construcao",
        "o `RUN` do AGR perde o `--require-hashes`",
        frozenset({"instalacao-fora-do-lockfile"}),
        lambda c: c.trocar("services/agr/Dockerfile", r"pip install --require-hashes --no-deps", "pip install --no-deps"),
    ),
    Mutacao(
        "pnpm-com-scripts-na-construcao",
        "o `RUN pnpm install` de um servico perde o `--ignore-scripts`",
        frozenset({"instalacao-fora-do-lockfile"}),
        lambda c: c.trocar("services/gwy/Dockerfile", r"pnpm install --frozen-lockfile --ignore-scripts", "pnpm install --frozen-lockfile"),
    ),
    Mutacao(
        "pip-sem-hashes-no-makefile",
        "o `bootstrap` volta a instalar do PyPI sem hash",
        frozenset({"instalacao-fora-do-lockfile"}),
        lambda c: c.trocar("Makefile", r"^\t@\$\(PYTHON\) -m venv \$\(VENV\)\n", "\t@$(PYTHON) -m venv $(VENV)\n\t@$(VENV_PYTHON) -m pip install --quiet --upgrade pip\n"),
    ),
    Mutacao(
        "servico-com-escrita",
        "os servicos do compose deixam de correr so de leitura",
        frozenset({"fs-so-de-leitura"}),
        lambda c: c.trocar(_COMPOSE, r"^  read_only: true$", "  read_only: false"),
    ),
    # -------------------------------------------------------------- egress
    Mutacao(
        "egress-apagado",
        "um servico deixa de declarar a sua lista de saidas",
        frozenset({"egress-em-falta"}),
        lambda c: c.apagar("services/gwy/egress.yaml"),
    ),
    Mutacao(
        "egress-permite-por-omissao",
        "a politica por omissao de um servico passa a `permitir`",
        frozenset({"egress-invalido"}),
        lambda c: c.trocar("services/com/egress.yaml", r"^por_omissao: negar$", "por_omissao: permitir"),
    ),
    Mutacao(
        "egress-para-qualquer-lado",
        "um destino `*`",
        frozenset({"egress-invalido"}),
        _destino_sem_nome,
    ),
    Mutacao(
        "egress-sem-dono",
        "uma lista de saidas para um servico que nenhum compose define",
        frozenset({"egress-orfao"}),
        lambda c: c.escrever("infra/egress/fantasma.yaml", "version: 1\nservico: fantasma\npor_omissao: negar\ndestinos: []\n"),
    ),
    # ------------------------------------------------------------ licencas
    Mutacao(
        "valkey-aprovado-pela-licenca",
        "o Valkey, travado pela D12, registado como `permitido`",
        frozenset({"licenca-estado-incoerente"}),
        lambda c: c.trocar(_LICENCAS, _ESTADO_DO_VALKEY, '    estado: permitido\n    ligacoes:\n      - "imagem:valkey/valkey"'),
    ),
    Mutacao(
        "busl-registada-como-permitida",
        "`MIT AND BUSL-1.1` registada como `permitido`",
        frozenset({"licenca-estado-incoerente"}),
        lambda c: c.trocar(_LICENCAS, _ESTADO_DO_MEILISEARCH, '    estado: permitido\n    ligacoes:\n      - "npm:meilisearch"'),
    ),
    Mutacao(
        "versao-em-uso-diferente-da-lida",
        "a licenca do Hono foi lida para outra versao que nao a do lockfile",
        frozenset({"licenca-versao-diferente"}),
        lambda c: c.trocar(_LICENCAS, r'(?<=componente: hono\n)    versao: "4\.13\.13"', '    versao: "4.12.0"'),
    ),
    Mutacao(
        "nao-adoptado-no-repositorio",
        "o Meilisearch (`MIT AND BUSL-1.1`, nao adoptado) entra num `package.json`",
        frozenset({"componente-presente-sem-aprovacao"}),
        _meilisearch_entra,
    ),
    Mutacao(
        "bloqueado-so-no-papel",
        "um componente registado como `bloqueado` que a lista de bloqueio nao bloqueia",
        # **Dois** achados, e nao um, desde o KAM-005: o BullMQ entrou no
        # repositorio (e dependencia de `packages/core-ts`), e por isso
        # declara-lo `bloqueado` deixa de ser so «bloqueado fora da lista de
        # bloqueio» — passa a ser tambem «componente presente sem aprovacao».
        # Os dois achados sao correctos e a mutacao continua a provar a regra
        # que vinha provar; o que mudou foi o mundo, nao o lint.
        frozenset({"bloqueado-fora-da-lista", "componente-presente-sem-aprovacao"}),
        lambda c: c.trocar(_LICENCAS, _ESTADO_DO_BULLMQ, '    estado: bloqueado\n    ligacoes:\n      - "npm:bullmq"'),
    ),
    Mutacao(
        "edicao-enterprise-sem-registo",
        "o Medusa deixa de dizer que partes sao Enterprise",
        frozenset({"ee-sem-registo"}),
        lambda c: c.trocar(_LICENCAS, r"    ee: >-\n      Proprietario desde 2026-08-11(?:.*\n)+?(?=    nota:)", ""),
    ),
    Mutacao(
        "componente-de-imagem-sem-licenca",
        "uma imagem declara um componente que o registo nao tem",
        frozenset({"componente-sem-licenca"}),
        lambda c: c.trocar(_INVENTARIO, r"^      - pgvector$", "      - pgvector\n      - postgis"),
    ),
    Mutacao(
        "excepcao-com-adr-que-nao-existe",
        "o Meilisearch admitido por «excepcao» que cita um ADR inexistente",
        frozenset({"licenca-sem-excepcao"}),
        lambda c: c.trocar(
            _LICENCAS, _ESTADO_DO_MEILISEARCH,
            # O numero vai a parte: por extenso, o gate 3 lia aqui uma referencia invalida.
            '    estado: excepcao\n    excepcao_adr: ADR-' + '999' + '\n'
            '    nota: Mutacao do canario, uma excepcao que cita um ADR que ninguem escreveu.\n'
            '    ligacoes:\n      - "npm:meilisearch"',
        ),
    ),
    Mutacao(
        "redis-rebaptizado",
        "o Redis com outro nome, licenca permitida e `estado: permitido`",
        frozenset({"licenca-estado-incoerente", "componente-obrigatorio-em-falta"}),
        lambda c: c.trocar(
            _LICENCAS,
            r'^  - componente: redis\n    versao: "8\.10\.2"\n    licenca: NOASSERTION\n((?:.*\n){3})    estado: pendente_de_decisao\n    decisao: D12\n',
            '  - componente: kv-fila\n    versao: "8.10.2"\n    licenca: BSD-3-Clause\n'
            '    data_verificacao: "2026-10-12"\n    fonte: "mutacao do canario"\n'
            '    estado_verificacao: INDÍCIO\n    estado: permitido\n',
        ),
    ),
    Mutacao(
        "linha-do-medusa-apagada",
        "o registo deixa de ter o Medusa, e com ele a sua edicao Enterprise",
        frozenset({"componente-obrigatorio-em-falta"}),
        lambda c: c.trocar(_LICENCAS, r"^  - componente: medusa\n(?:    .*\n|      .*\n)+\n", ""),
    ),
    # ------------------------------------------------------- renovate e CI
    Mutacao(
        "renovate-com-ficheiro-sombra",
        "um `renovate.json` ao lado, com automerge e sem quarentena",
        frozenset({"configuracao-sombra"}),
        lambda c: c.escrever("renovate.json", '{"automerge": true, "minimumReleaseAge": null}\n'),
    ),
    Mutacao(
        "automerge-por-preset",
        "`extends` passa a incluir `:automergeAll`",
        frozenset({"automerge-ligado"}),
        lambda c: c.trocar("renovate.json5", r'^    "group:monorepos",$', '    "group:monorepos",\n    ":automergeAll",'),
    ),
    Mutacao(
        "quarentena-furada-por-tipo-de-actualizacao",
        "`patch: { minimumReleaseAge: null, automerge: true }`",
        frozenset({"quarentena-desligada", "automerge-ligado"}),
        lambda c: c.trocar("renovate.json5", r"^  packageRules: \[$", "  patch: { minimumReleaseAge: null, automerge: true },\n  packageRules: ["),
    ),
    Mutacao(
        "todos-os-segredos-por-tojson",
        "um passo do workflow recebe `toJSON(secrets)`, em maiusculas",
        frozenset({"chave-estatica-no-ci"}),
        lambda c: c.trocar(_WORKFLOW, r"^env:\n", "env:\n  TUDO: ${{ toJSON(SECRETS) }}\n"),
    ),
    Mutacao(
        "quarentena-a-zero",
        "`minimumReleaseAge` passa a zero dias",
        frozenset({"quarentena-desligada"}),
        lambda c: c.trocar("renovate.json5", r'^  minimumReleaseAge: "7 days",$', '  minimumReleaseAge: "0 days",'),
    ),
    Mutacao(
        "quarentena-furada-por-regra",
        "uma `packageRule` dispensa a quarentena para um pacote",
        frozenset({"quarentena-desligada"}),
        lambda c: c.trocar("renovate.json5", r"^  packageRules: \[$", '  packageRules: [\n    { matchPackageNames: ["hono"], minimumReleaseAge: null },'),
    ),
    Mutacao(
        "automerge-ligado",
        "o `automerge` de topo passa a `true`",
        frozenset({"automerge-ligado"}),
        lambda c: c.trocar("renovate.json5", r"^  automerge: false,$", "  automerge: true,"),
    ),
    Mutacao(
        "excepcao-de-seguranca-sem-revisores",
        "a excepcao de seguranca deixa de ter revisores",
        frozenset({"excepcao-de-seguranca-sem-revisao"}),
        lambda c: c.trocar("renovate.json5", r'^    reviewers: \["team:plataforma", "team:seguranca"\],$', "    reviewers: [],"),
    ),
    Mutacao(
        "chave-estatica-no-workflow",
        "um passo do workflow le uma chave do cofre de segredos",
        frozenset({"chave-estatica-no-ci"}),
        lambda c: c.trocar(_WORKFLOW, r"^env:\n", "env:\n  CHAVE_DO_REGISTO: ${{ secrets.CHAVE_DO_REGISTO }}\n"),
    ),
)

#: Regras que tem de ter, pelo menos, este numero de mutacoes. Retirar uma
#: mutacao da lista acima sem mexer aqui falha o canario.
MINIMO_POR_REGRA = {
    "imagem-sem-digest": 8,
    "imagem-fora-do-inventario": 1,
    "imagem-nao-resolvida": 2,
    "ficheiro-ilegivel": 3,
    "inventario-entrada-morta": 1,
    "lancador-nao-declarado": 2,
    "cosign-obrigatorio": 2,
    "instalacao-em-runtime": 6,
    "arranque-nao-verificavel": 1,
    "instalacao-fora-do-lockfile": 5,
    "licenca-sem-excepcao": 1,
    "componente-obrigatorio-em-falta": 2,
    "configuracao-sombra": 1,
    "fs-so-de-leitura": 1,
    "egress-em-falta": 1,
    "egress-invalido": 2,
    "egress-orfao": 1,
    "licenca-estado-incoerente": 3,
    "licenca-versao-diferente": 1,
    "componente-presente-sem-aprovacao": 1,
    "bloqueado-fora-da-lista": 1,
    "ee-sem-registo": 1,
    "componente-sem-licenca": 1,
    "quarentena-desligada": 3,
    "automerge-ligado": 3,
    "excepcao-de-seguranca-sem-revisao": 1,
    "chave-estatica-no-ci": 2,
}


def copiar(origem: Path, destino: Path) -> None:
    def ignorar(_directorio: str, nomes: list[str]) -> set[str]:
        return {nome for nome in nomes if nome in _FORA_DA_COPIA}

    shutil.copytree(origem, destino, ignore=ignorar, symlinks=False, dirs_exist_ok=True)
    for relativo in _DE_DOCS:
        fonte = origem / relativo
        if fonte.is_dir():
            shutil.copytree(fonte, destino / relativo, dirs_exist_ok=True)
        elif fonte.is_file():
            (destino / relativo).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(fonte, destino / relativo)


def correr(raiz: Path, mutacoes: tuple[Mutacao, ...] = MUTACOES) -> tuple[list[str], list[str]]:
    """Corre o canario. Devolve (linhas do relatorio, falhas)."""
    from .cli import executar_todas

    relatorio: list[str] = []
    falhas: list[str] = []

    cobertura: dict[str, int] = {}
    for mutacao in mutacoes:
        for regra in mutacao.regras:
            cobertura[regra] = cobertura.get(regra, 0) + 1
    for regra, minimo in sorted(MINIMO_POR_REGRA.items()):
        if cobertura.get(regra, 0) < minimo:
            falhas.append(
                f"a regra `{regra}` tem {cobertura.get(regra, 0)} mutacao(oes); "
                f"o minimo e {minimo}"
            )

    with tempfile.TemporaryDirectory(prefix="kamba-canario-") as temporario:
        copia_raiz = Path(temporario) / "repo"
        copiar(raiz, copia_raiz)

        base = executar_todas(copia_raiz)
        if base:
            falhas.append(
                f"linha de base vermelha: a copia sem mutacao tem {len(base)} "
                "achado(s). Sem linha de base verde, um vermelho nao prova nada."
            )
            for achado in base[:10]:
                falhas.append(f"    {achado}")
            return relatorio, falhas

        copia = Copia(copia_raiz)
        for mutacao in mutacoes:
            try:
                mutacao.aplicar(copia)
            except NaoSeAplica as excepcao:
                falhas.append(f"{mutacao.nome}: a mutacao ja nao se aplica — {excepcao}")
                copia.repor()
                continue
            try:
                regras = {achado.regra for achado in executar_todas(copia_raiz)}
            except Exception as excepcao:  # noqa: BLE001 - qualquer erro e falha do canario
                regras = {f"erro: {type(excepcao).__name__}: {excepcao}"}
            finally:
                copia.repor()
            if regras == set(mutacao.regras):
                relatorio.append(f"    vermelho  {mutacao.nome}  [{', '.join(sorted(regras))}]")
            elif not regras:
                falhas.append(
                    f"{mutacao.nome}: **sobreviveu** — {mutacao.descricao}, e nenhuma "
                    "verificacao deu por isso"
                )
            else:
                falhas.append(
                    f"{mutacao.nome}: esperava [{', '.join(sorted(mutacao.regras))}] e "
                    f"obteve [{', '.join(sorted(regras))}]"
                )

        depois = executar_todas(copia_raiz)
        if depois:
            falhas.append(
                "a copia nao voltou ao estado inicial depois das mutacoes: uma "
                "mutacao nao foi reposta, e as seguintes correram sobre ela"
            )
    return relatorio, falhas


def main(raiz: Path) -> int:
    relatorio, falhas = correr(raiz)
    if falhas:
        print(f"supply_chain: canario: {len(falhas)} falha(s)", file=sys.stderr)
        for falha in falhas:
            print(f"  - {falha}", file=sys.stderr)
        return 1
    for linha in relatorio:
        print(linha)
    print(
        f"supply_chain: canario: linha de base verde; {len(relatorio)} mutacoes, "
        f"{len(relatorio)} vermelhas pela regra esperada, 0 sobreviventes"
    )
    return 0
