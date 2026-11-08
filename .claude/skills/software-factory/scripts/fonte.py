"""A arvore que se mede e a da origem, nao a tua: leitura pelo `git`, sem checkout.

O `vagas.py` le o disco, e o disco e o teu ramo — um ID livre ou um ticket aberto
no teu checkout pode ja estar fundido na `main` (medido no KAM-165, e outra vez a
2026-11-08 com o KAM-137). Os dois guioes do KAM-185 leem tudo de uma *ref* e de
objectos do `git`, pelo que medem a mesma arvore seja qual for o directorio de onde
os corres — **e o `git` corre sempre a partir da raiz do repositorio**: o `ls-tree`
e o `archive` resolvem os caminhos pelo directorio corrente, e a partir de `specs/`
o `ls-tree ... db/migrations/versions/` dava 0 linhas com codigo 0 (achado da
revisao adversarial). Os caminhos saem sem aspas (`core.quotepath=off`), para que
um nome com acento continue a acabar em `.md`.

**Os codigos de saida leem-se sempre.** O `merge-base` entre as duas linhas sem
antepassado comum (`origin` e `publico`) sai com 1 e sem saida, e quem so captura a
saida le o silencio como «nada a mais» (KAM-180). Aqui um comando que falha levanta,
salvo onde o 1 e uma resposta (o `merge-tree` com conflitos).
"""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path

REPO = "albinoJimy/kamba-plataforma"
REMOTO = "publico"
BASE = "refs/remotes/publico/main"

#: O que o `lint_bloco` precisa para correr numa arvore materializada. **Pastas
#: inteiras, e nao a lista dos modulos que ele importa:** a primeira versao listou
#: quatro, e o `lint_refs` puxa o `kamba_yaml`, que puxa... o `lint_handoff` — cada
#: `import` novo em qualquer deles partia esta medicao. Custa 7,5 s por arvore
#: contra 2,9 s, e guarda-se por objecto. Faltar um modulo continua a **levantar**.
PARA_O_PISO = ("specs", "tools", "ci")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


class FalhaDoGit(RuntimeError):
    pass


def correr(*args: str, aceitar: tuple[int, ...] = (0,), cwd: str | None = None) -> tuple[int, str]:
    """Corre um comando e devolve `(codigo, stdout)`. Levanta fora de `aceitar`."""
    feito = subprocess.run(list(args), capture_output=True, text=True, encoding="utf-8",
                           errors="replace", cwd=cwd)
    if feito.returncode not in aceitar:
        raise FalhaDoGit(f"{' '.join(args[:4])}... saiu com {feito.returncode}: "
                         f"{feito.stderr.strip()[:300]}")
    return feito.returncode, feito.stdout


_RAIZES: dict[str, str] = {}


def raiz() -> str:
    """A raiz do repositorio do directorio corrente, guardada por directorio."""
    aqui = os.getcwd()
    if aqui not in _RAIZES:
        _RAIZES[aqui] = correr("git", "rev-parse", "--show-toplevel")[1].strip()
    return _RAIZES[aqui]


def git_com_codigo(*args: str, aceitar: tuple[int, ...] = (0,)) -> tuple[int, str]:
    return correr("git", "-c", "core.quotepath=off", *args, aceitar=aceitar, cwd=raiz())


def git(*args: str, aceitar: tuple[int, ...] = (0,)) -> str:
    return git_com_codigo(*args, aceitar=aceitar)[1]


def actualizar_base() -> str:
    """O `fetch` com *refspec*: sem ele so se move o `FETCH_HEAD` (SKILL §0)."""
    git("fetch", "-q", REMOTO, f"main:{BASE}", "--force")
    return git("rev-parse", BASE).strip()


@dataclass(frozen=True)
class Arvore:
    """Uma arvore do `git` lida por objectos: um *commit*, uma *ref* ou um *tree*."""

    ref: str

    def ler(self, caminho: str) -> str | None:
        codigo, saida = git_com_codigo("show", f"{self.ref}:{caminho}", aceitar=(0, 128))
        return saida if codigo == 0 else None

    def listar(self, pasta: str) -> list[str]:
        saida = git("ls-tree", "--name-only", f"{self.ref}", f"{pasta.rstrip('/')}/")
        return [linha for linha in saida.splitlines() if linha]


def fundir(base: str, ponta: str) -> tuple[str, list[str]]:
    """O `merge-tree` sem tocar em nada: devolve `(tree, ficheiros_em_conflito)`.

    Com conflitos o `git` escreve na mesma uma arvore (com marcadores) e sai com 1;
    quem a medir tem de saber que ela nao e a arvore que vai fundir.
    """
    codigo, saida = git_com_codigo("merge-tree", "--write-tree", "--name-only",
                                   base, ponta, aceitar=(0, 1))
    linhas = saida.splitlines()
    arvore = linhas[0].strip()
    conflitos: list[str] = []
    if codigo == 1:
        for linha in linhas[1:]:
            if not linha.strip():
                break
            conflitos.append(linha.strip())
    return arvore, conflitos


def base_comum(a: str, b: str) -> str | None:
    """O `merge-base`, com o 1 lido como «sem antepassado comum» e nao como vazio."""
    codigo, saida = git_com_codigo("merge-base", a, b, aceitar=(0, 1))
    return saida.strip() if codigo == 0 else None


def mudados(antes: str, depois: str) -> list[tuple[str, str]]:
    """`(estado, caminho)` entre duas arvores, sem renomeacoes."""
    saida = git("diff", "--name-status", "--no-renames", antes, depois)
    return [tuple(linha.split("\t", 1)) for linha in saida.splitlines() if "\t" in linha]  # type: ignore[misc]


def piso_declarado(ref: str) -> int | None:
    """A constante `MINIMO_DE_BLOCOS_MEDIDOS` escrita numa arvore, sem a materializar."""
    import superficies
    texto = Arvore(ref).ler("tools/lint_bloco/lint.py")
    achado = superficies.PISO.search(texto or "")
    return int(achado.group(1)) if achado else None


_PISOS: dict[str, tuple[int, int]] = {}


def medir_piso(ref: str) -> tuple[int, int]:
    """`(medidos, MINIMO_DE_BLOCOS_MEDIDOS)` do `lint_bloco` **da propria arvore**.

    Corre num processo novo sobre a arvore materializada, para que o piso lido seja
    a constante daquela arvore e nao a do teu checkout. Guarda por objecto: a mesma
    arvore mede-se uma vez.
    """
    chave = git("rev-parse", f"{ref}^{{tree}}").strip()
    if chave in _PISOS:
        return _PISOS[chave]
    pasta = Path(tempfile.mkdtemp(prefix="kam185-"))
    try:
        _, dados = correr_bytes("git", "archive", "--format=tar", chave, *PARA_O_PISO, cwd=raiz())
        with tarfile.open(fileobj=io.BytesIO(dados)) as tar:
            tar.extractall(pasta, filter="data")
        programa = ("import sys,pathlib; sys.path.insert(0,'tools')\n"
                    "from lint_bloco import lint\n"
                    "_,_,n=lint.verificar(pathlib.Path('.'))\n"
                    "print(n['medidos'], lint.MINIMO_DE_BLOCOS_MEDIDOS)")
        ambiente = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        feito = subprocess.run([sys.executable, "-c", programa], cwd=pasta, env=ambiente,
                               capture_output=True, text=True, encoding="utf-8")
        if feito.returncode != 0:
            raise FalhaDoGit(f"o lint_bloco nao correu na arvore {chave[:8]}: "
                             f"{feito.stderr.strip()[-300:]}")
        medidos, piso = (int(x) for x in feito.stdout.split())
    finally:
        shutil.rmtree(pasta, ignore_errors=True)
    _PISOS[chave] = (medidos, piso)
    return medidos, piso


def correr_bytes(*args: str, cwd: str | None = None) -> tuple[int, bytes]:
    feito = subprocess.run(list(args), capture_output=True, cwd=cwd)
    if feito.returncode != 0:
        raise FalhaDoGit(f"{' '.join(args[:3])}... saiu com {feito.returncode}: "
                         f"{feito.stderr.decode('utf-8', 'replace').strip()[:300]}")
    return feito.returncode, feito.stdout

