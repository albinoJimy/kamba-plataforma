"""Que ficheiros pertencem a que superficie — e os que deviam e nao pertencem.

Varre-se `git ls-files`, como o gate 3: as copias em `.claude/worktrees/*` sao
repositorios inteiros, ignorados pelo git e visiveis a qualquer `os.walk`.

**Sentinelas.** Uma superficie e uma lista de padroes de caminho, e isso tem um
modo de falha silencioso: no dia em que alguem puser uma migracao em
`services/com/migrations/versions/` ou um schema de evento em
`packages/contracts/`, o padrao nao bate, o lint ve zero ficheiros e fica verde.
Uma sentinela e um padrao **largo** com a forma de uma superficie; um ficheiro
que bate numa sentinela e nao esta na superficie (nem em `fora_de_ambito`)
falha o gate, com a instrucao de o declarar.
"""

from __future__ import annotations

import fnmatch
import subprocess
from pathlib import Path

from .achados import SENTINELA, Achado
from .dicionario import POLITICA, ConfiguracaoInvalida, Politica


def ficheiros_do_git(raiz: Path) -> list[str]:
    """Os ficheiros seguidos pelo git **e** os novos ainda por seguir.

    Inclui os nao seguidos (mas nao os ignorados) para que o lint corrido antes
    do `git add` veja a migracao que se acabou de escrever; no CI nao ha
    diferenca, porque a arvore esta limpa.
    """
    try:
        resultado = subprocess.run(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            cwd=raiz,
            capture_output=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as excepcao:
        raise ConfiguracaoInvalida(
            f"nao foi possivel listar os ficheiros do git em {raiz}: {excepcao}"
        ) from excepcao
    caminhos = []
    for bruto in resultado.stdout.decode("utf-8", errors="replace").split("\0"):
        if bruto and (raiz / bruto).is_file():
            caminhos.append(bruto)
    return sorted(set(caminhos))


def _bate(caminho: str, padroes: list[str]) -> bool:
    # `fnmatchcase`, e nao `fnmatch`: o segundo normaliza a caixa em Windows e
    # nao em Linux, e o mesmo repositorio dava superficies diferentes.
    return any(fnmatch.fnmatchcase(caminho, padrao) for padrao in padroes)


def repartir(ficheiros: list[str], politica: Politica) -> tuple[dict[str, list[str]], list[Achado]]:
    """Devolve {superficie: ficheiros} e os achados de sentinela."""
    superficies = {
        nome: [f for f in ficheiros if _bate(f, padroes) and not _bate(f, politica.fora_de_ambito)]
        for nome, padroes in politica.superficies.items()
    }
    achados: list[Achado] = []
    for ficheiro in ficheiros:
        if _bate(ficheiro, politica.fora_de_ambito):
            continue
        for padrao, superficie in politica.sentinelas:
            # A sentinela compara em minusculas; a superficie e sensivel a caixa.
            # `registry/x.YAML` bate aqui e nao bate la — e por isso falha, em vez
            # de ficar de fora das duas.
            if fnmatch.fnmatchcase(ficheiro.lower(), padrao) and ficheiro not in superficies[superficie]:
                achados.append(
                    Achado(
                        ficheiro,
                        0,
                        SENTINELA,
                        f"tem a forma de um ficheiro da superficie `{superficie}` (`{padrao}`) e "
                        f"nenhum padrao de {POLITICA} o cobre. O gate 3b nao o esta a ler: "
                        "acrescente o caminho a `superficies`, ou declare-o em `fora_de_ambito` "
                        "com a razao",
                    )
                )
                break
    return superficies, achados
