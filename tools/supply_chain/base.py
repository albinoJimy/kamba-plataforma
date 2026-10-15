"""O que os verificadores partilham: achados, erros de configuracao e a arvore."""

from __future__ import annotations

import dataclasses
import os
from pathlib import Path


class ConfiguracaoInvalida(RuntimeError):
    """Um ficheiro de politica em falta ou malformado.

    Nao e um achado: e saida 2. Um ficheiro de politica ilegivel nao pode
    parecer um repositorio conforme.
    """


@dataclasses.dataclass(frozen=True)
class Achado:
    #: Identificador estavel da regra. O canario confere-o: uma mutacao tem de
    #: ser apanhada **por esta regra**, e nao por outra qualquer.
    regra: str
    ficheiro: str
    linha: int
    mensagem: str

    def __str__(self) -> str:
        onde = f"{self.ficheiro}:{self.linha}" if self.linha else self.ficheiro
        return f"[{self.regra}] {onde}: {self.mensagem}"


#: Directorios que nunca se analisam: nao sao fonte, sao resultado.
#:
#: `build` e `dist` **nao** estao aqui, ao contrario do que acontece no
#: `lint_arch`: um `build/Dockerfile` ou um `infra/dist/compose.yml` sao fonte, e
#: saltar o directorio em qualquer profundidade era uma forma de os esconder.
SALTAR_DIRECTORIOS = frozenset(
    {
        ".git",
        "node_modules",
        ".venv",
        "venv",
        "__pycache__",
        ".pnpm-store",
        ".mypy_cache",
        ".ruff_cache",
    }
)

#: Caminhos (relativos a raiz) que se excluem do varrimento.
SALTAR_CAMINHOS = (
    # Fixtures da lista de bloqueio: contem, de proposito, imagens proibidas e
    # sem digest. Sao o teste de outro controlo, nao uma violacao deste.
    "tools/lint_arch/tests/fixtures",
    # Arvores de trabalho paralelas: copias completas do repositorio.
    ".claude/worktrees",
    # Artefactos de execucoes do CI.
    "ci/coverage",
    "ci/sbom",
)


def percorrer(raiz: Path):
    """Todos os ficheiros sob `raiz`, por ordem, sem o que e artefacto.

    Varre o disco e nao `git ls-files`, de proposito: os testes e o canario
    correm sobre arvores temporarias que nao sao repositorios, e um ficheiro por
    seguir (o `.env` local, por exemplo) **decide** que imagem corre na maquina
    de quem o tem.
    """
    for directorio, subdirectorios, ficheiros in os.walk(raiz, onerror=None):
        base = Path(directorio)
        relativo = base.relative_to(raiz).as_posix()
        prefixo = "" if relativo == "." else f"{relativo}/"
        subdirectorios[:] = sorted(
            nome
            for nome in subdirectorios
            if nome not in SALTAR_DIRECTORIOS
            and not any(
                f"{prefixo}{nome}" == salto or f"{prefixo}{nome}".startswith(salto + "/")
                for salto in SALTAR_CAMINHOS
            )
        )
        for nome in sorted(ficheiros):
            caminho = base / nome
            try:
                if not caminho.is_file():
                    continue
            except OSError:
                continue
            yield caminho


def relativo(caminho: Path, raiz: Path) -> str:
    try:
        return caminho.relative_to(raiz).as_posix()
    except ValueError:
        # Um dos dois foi resolvido e o outro nao (em Windows, o nome curto
        # `ARMAND~1` contra o longo): compara-se pela forma resolvida.
        return caminho.resolve().relative_to(raiz.resolve()).as_posix()


def ler_texto(caminho: Path) -> str:
    # Sem o BOM: com ele, a primeira chave de um YAML deixava de ser `services`
    # e o ficheiro lia-se como um compose sem servicos — conforme, sem ter sido lido.
    texto = caminho.read_text(encoding="utf-8", errors="replace")
    return texto.lstrip("\ufeff").replace("\r\n", "\n")
