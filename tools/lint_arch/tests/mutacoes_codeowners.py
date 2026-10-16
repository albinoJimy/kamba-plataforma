"""Prova por mutacao do gate dos caminhos do `CODEOWNERS` (KAM-154).

    python tools/lint_arch/tests/mutacoes_codeowners.py [filtro]
    python tools/lint_arch/tests/mutacoes_codeowners.py --aplicaveis

Um teste que passa nao prova que morde. Isto prova: copia o codigo para um
directorio temporario **fora do repositorio**, confirma que a linha de base esta
verde, e aplica **uma** alteracao deliberadamente errada de cada vez — a regra
pendurada deixa de ser acusada, o `*` volta a ser excepcionado pelo nome, a barra
final deixa de exigir directorio, o `**` deixa de valer zero segmentos — e exige
que a bateria fique vermelha. O repositorio nao e tocado.

**Porque nao entra em `mutacoes.py`, ao lado.** Aquele e o arreio do gate 4: copia
`tools`, `packages`, `services`, `libs`, `ci/thresholds.yaml` e o `Makefile`, e as
baterias que exige sao `test_coverage_gate.py` e `test_makefile.py`. Uma mutacao
do resolvedor de `CODEOWNERS` posta la sobrevivia **por construcao**, porque
nenhuma dessas duas baterias o corre — uma prova que da por provado o que nunca
correu, que e o defeito que o proprio `mutacoes.py` nomeia no seu cabecalho. Dois
arreios, cada um com o seu alvo e a sua bateria.

**Tres casos nao correm aqui, e a razao e permanente.** A copia leva `tools/` e
mais nada: nao tem `CODEOWNERS` na raiz nem arvore de git, pelo que os tres casos
que medem o **ficheiro real** nao tem o que medir. Ficam marcados com
`@NO_REPOSITORIO` na bateria, com a condicao escrita — e nao excluidos daqui por
nome, que era como um caso que passasse a nao correr no repositorio passava
calado. A prova corre a bateria inteira; o `unittest` salta os tres e di-lo.

**Uma mutacao fica de fora, com a prova de que e equivalente.** Trocar o `.*` de
um `**` final por `[^/]*` sobrevive, e **nao e um teste em falta**: para a
pergunta deste gate — «algum candidato casa?» — as duas sao equivalentes, porque
os directorios derivam-se dos ficheiros. Se existe `P/x1/.../xn`, entao `P/x1`
esta nos directorios e casa com `P/[^/]*`; o inverso e imediato. Verificado por
varredura exaustiva sobre 60 arvores x 7 padroes com `**` final: **0
divergencias**. Uma entrada que sobrevivesse sempre poria o arreio vermelho para
sempre, o que e pior do que a ausencia dela registada aqui.

Nao faz parte de nenhum gate. Corre-se quando se mexe no `codeowners.py` e o
resultado registra-se na analise do ticket. Uma mutacao que **sobreviva** e um
teste em falta.

Vive em `tests/` e nao se chama `test_*.py`: nao e descoberto pelo `unittest`
nem medido pela cobertura.
"""

from __future__ import annotations

import concurrent.futures
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]

GATE = "tools/lint_arch/codeowners.py"
ESTRUTURA = "tools/lint_arch/structure.py"

#: (nome, ficheiro, texto antigo, texto novo). O nome diz o defeito que a
#: mutacao introduz, nao a linha que troca.
MUTACOES: list[tuple[str, str, str, str]] = [
    # --- o achado, que e o que este ticket entrega ---
    ("achado: uma regra pendurada deixa de ser acusada", GATE,
     "        if not casou:\n", "        if False:\n"),
    ("achado: a mensagem deixa de dizer que a area fica sem dono", GATE,
     '                "    O GitHub **nao recusa** uma regra assim: ignora-a, e a area "\n'
     '                "que ela devia cobrir fica sem dono, em silencio.\\n"\n',
     ""),
    ("achado: o gate deixa de ser chamado pela estrutura", ESTRUTURA,
     "    problems.extend(codeowners.check(root, caminhos=caminhos))\n", ""),

    # --- a excepcao que a semantica tornou desnecessaria ---
    ("estrela: o `*` volta a ser excepcionado pelo nome", GATE,
     "    for regra in regras(texto):\n",
     "    for regra in regras(texto):\n        if regra.padrao == \"*\":\n            continue\n"),

    # --- a semantica de glob, que e a razao de nao ser `[ -e ]` ---
    ("glob: a barra final deixa de exigir directorio", GATE,
     "    so_directorios = padrao.endswith(\"/\")\n",
     "    so_directorios = False\n"),
    ("glob: um ficheiro passa a satisfazer um padrao de directorio", GATE,
     "    alvos = directorios if so_directorios else (ficheiros | directorios)\n",
     "    alvos = ficheiros | directorios\n"),
    ("glob: o `*` passa a atravessar a barra", GATE,
     '                partes.append("[^/]*")\n',
     '                partes.append(".*")\n'),
    ("glob: o `**/` deixa de valer zero segmentos", GATE,
     '                    partes.append("(?:[^/]+/)*")\n',
     '                    partes.append("(?:[^/]+/)+")\n'),
    ("glob: um padrao sem barra deixa de casar em qualquer nivel", GATE,
     '        corpo = "(?:[^/]+/)*" + corpo\n', ""),
    ("glob: a barra no meio deixa de ancorar", GATE,
     '        ancorado = "/" in nucleo\n', "        ancorado = False\n"),
    ("glob: a barra inicial deixa de ancorar", GATE,
     "        ancorado, nucleo = True, nucleo[1:]\n",
     "        ancorado, nucleo = False, nucleo[1:]\n"),
    ("glob: a expressao deixa de ancorar no fim e um prefixo resolve", GATE,
     '    return re.compile("^" + corpo + "$"), so_directorios\n',
     '    return re.compile("^" + corpo), so_directorios\n'),

    # --- fail-closed sobre o que o GitHub nao suporta ---
    ("suporte: as construcoes nao suportadas passam a ser resolvidas", GATE,
     "    for caracter, razao in NAO_SUPORTADOS.items():\n",
     "    for caracter, razao in {}.items():\n"),
    ("suporte: o `?` deixa de ser recusado", GATE,
     '    "?": (\n', '    "\\x00": (\n'),

    # --- a arvore, que e a do git ---
    ("arvore: os directorios deixam de ser derivados dos ficheiros", GATE,
     "        for corte in range(1, len(partes)):\n",
     "        for corte in range(1, 1):\n"),
    ("arvore: a leitura passa a aceitar o que o git nao segue", GATE,
     '            ["git", "ls-files", "-z"],\n',
     '            ["git", "ls-files", "-z", "--others"],\n'),

    # --- a leitura do ficheiro ---
    ("leitura: um BOM volta a inventar uma regra", GATE,
     'encoding="utf-8-sig"', 'encoding="utf-8"'),
    ("leitura: um comentario passa a contar como regra", GATE,
     '        if not linha or linha.startswith("#"):\n',
     "        if not linha:\n"),
    ("leitura: o numero da linha deixa de ser o do ficheiro", GATE,
     "    for numero, bruta in enumerate(texto.splitlines(), start=1):\n",
     "    for numero, bruta in enumerate(texto.splitlines()):\n"),
]

#: O que a copia leva. So `tools`: o resolvedor nao le mais nada, e as *fixtures*
#: vivem dentro de `tools/lint_arch/tests/`.
COPIAR = ("tools",)
IGNORAR = shutil.ignore_patterns("node_modules", "dist", "__pycache__", "*.egg-info")

#: A bateria que uma mutacao tem de por vermelha.
BATERIA = "test_codeowners.py"


def _copiar(destino: Path) -> None:
    for relativo in COPIAR:
        origem, alvo = RAIZ / relativo, destino / relativo
        alvo.parent.mkdir(parents=True, exist_ok=True)
        if origem.is_dir():
            shutil.copytree(origem, alvo, ignore=IGNORAR)
        else:
            shutil.copy(origem, alvo)


def _passa(copia: Path) -> bool:
    """`True` se a bateria passar na copia."""
    ambiente = dict(os.environ)
    ambiente["PYTHONPATH"] = str(copia / "tools")
    ambiente["PYTHONDONTWRITEBYTECODE"] = "1"
    resultado = subprocess.run(
        [
            sys.executable, "-m", "unittest",
            "discover", "-s", "lint_arch/tests", "-t", ".", "-p", BATERIA,
        ],
        cwd=copia / "tools",
        env=ambiente,
        capture_output=True,
    )
    return resultado.returncode == 0


def aplicaveis() -> int:
    falhas = 0
    for nome, ficheiro, velho, novo in MUTACOES:
        texto = (RAIZ / ficheiro).read_text(encoding="utf-8")
        if texto.count(velho) != 1 or velho == novo:
            print(f"MUTACAO NAO APLICAVEL ({texto.count(velho)} ocorrencias): {nome}")
            falhas += 1
    print(f"{len(MUTACOES)} mutacoes, {falhas} nao aplicaveis")
    return 1 if falhas else 0


def _paralelo() -> int:
    bruto = os.environ.get("KAMBA_MUTACOES_PARALELO", "8")
    try:
        return max(1, int(bruto))
    except ValueError:
        return 8


def _correr(mutacao: tuple[str, str, str, str]) -> tuple[str, bool]:
    """Aplica uma mutacao na sua propria copia. Devolve (nome, apanhada)."""
    nome, ficheiro, velho, novo = mutacao
    copia = Path(tempfile.mkdtemp(prefix="kam150-mutacao-"))
    try:
        assert RAIZ not in copia.parents, "a copia tem de ficar fora do repositorio"
        _copiar(copia)
        alvo = copia / ficheiro
        texto = alvo.read_text(encoding="utf-8")
        alvo.write_text(texto.replace(velho, novo), encoding="utf-8")
        return nome, not _passa(copia)
    finally:
        shutil.rmtree(copia, ignore_errors=True)


def main(argv: list[str]) -> int:
    if "--aplicaveis" in argv:
        return aplicaveis()
    filtro = argv[0] if argv else ""
    escolhidas = [m for m in MUTACOES if filtro in m[0]]
    if not escolhidas:
        print(f"nenhuma mutacao com `{filtro}` no nome", file=sys.stderr)
        return 2
    if aplicaveis() != 0:
        return 1

    # A linha de base, sem mutacao nenhuma. Sem isto, qualquer copia quebrada
    # dava a prova por feita: foi o defeito que a prova do KAM-004 teve.
    base = Path(tempfile.mkdtemp(prefix="kam150-base-"))
    try:
        _copiar(base)
        if not _passa(base):
            print("LINHA DE BASE VERMELHA: nada foi provado", file=sys.stderr)
            return 1
    finally:
        shutil.rmtree(base, ignore_errors=True)
    print("linha de base verde")

    resultados: dict[str, bool] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=_paralelo()) as piscina:
        for nome, apanhada in piscina.map(_correr, escolhidas):
            resultados[nome] = apanhada
            print(f"  {'APANHADA   ' if apanhada else 'SOBREVIVEU '} {nome}")

    sobreviventes = [n for n, apanhada in resultados.items() if not apanhada]
    print(
        f"\n{len(resultados)} mutacoes, {len(resultados) - len(sobreviventes)} apanhadas, "
        f"{len(sobreviventes)} sobreviventes"
    )
    if sobreviventes:
        print("\nSOBREVIVENTES (cada uma e um teste em falta):", file=sys.stderr)
        for nome in sobreviventes:
            print(f"  - {nome}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
