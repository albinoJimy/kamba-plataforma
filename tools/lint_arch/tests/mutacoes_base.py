"""Prova por mutacao do instrumento da base do ramo (KAM-180).

    python tools/lint_arch/tests/mutacoes_base.py [filtro]
    python tools/lint_arch/tests/mutacoes_base.py --aplicaveis

Um teste que passa nao prova que morde. Isto prova: copia o codigo para um
directorio temporario **fora do repositorio**, confirma que a linha de base esta
verde, e aplica **uma** alteracao deliberadamente errada de cada vez — a decisao
passa a vir da pasta `.claude/skills/`, o codigo de saida do `merge-base` deixa
de ser lido, a origem passa a sair da coluna do valor novo, o *reflog* passa a
ler-se pela ultima entrada, o «nao sei» passa a valer zero — e exige que a
bateria fique vermelha. O repositorio nao e tocado.

**As duas que o ticket nomeia** sao a primeira (`pasta`) e a segunda
(`codigo-de-saida`). As outras cinco estao aqui porque a implementacao as corre
de verdade: cada uma e uma forma de responder «onde estou agora» em vez de «fui
cortado», que e o defeito que o ticket existe para fechar.

**Porque nao entra em `mutacoes.py` nem em `mutacoes_codeowners.py`, ao lado.**
Aquele e o arreio do *gate* 4 e este o do resolvedor de `CODEOWNERS`; nenhum dos
dois corre a `test_base.py`, pelo que uma mutacao do `base.py` posta la
sobrevivia **por construcao** — uma prova que da por provado o que nunca correu,
que e o defeito que o proprio `mutacoes.py` nomeia no seu cabecalho. Tres
arreios, cada um com o seu alvo e a sua bateria.

**Dois casos da bateria nao correm aqui, e a razao e permanente.** A copia leva
`tools/` e mais nada: nao tem arvore de git na raiz, pelo que os dois casos de
`TestNoRepositorioReal` — que medem **este** repositorio — nao tem o que medir.
Ficam marcados com `skipUnless` na bateria, com a condicao escrita, e nao
excluidos daqui por nome: era assim que um caso que passasse a nao correr no
repositorio passava calado. Os restantes constroem os seus proprios repositorios
em directorios temporarios, *worktrees* incluidos, pelo que correm na copia tal
como correm aqui.

**Uma forma de errar nao tem mutacao propria, e a razao e que seria a mesma
prova.** Decidir pela **mensagem** do *reflog* (`branch: Reset to
refs/remotes/publico/main`) produz o mesmo veredicto errado que a mutacao
`coluna-nova`: as duas leem algo que reflecte a **reparacao** e nao a origem, e o
caso que as apanha e o mesmo (`TestORamoReparado`). Escrever a segunda era
duplicar a prova, nao acrescentar uma. Que a mensagem nao e guardada esta fixado
em `test_a_entrada_descarta_a_mensagem`.

Nao faz parte de nenhum gate — ligar isto a um portao e decisao do fundador, como
o ticket escreve. Corre-se quando se mexe no `base.py`, e o resultado registra-se
na verificacao do ticket. Uma mutacao que **sobreviva** e um teste em falta.

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

ALVO = "tools/lint_arch/base.py"

#: (nome, ficheiro, texto antigo, texto novo). O nome diz o defeito que a
#: mutacao introduz, nao a linha que troca.
MUTACOES: list[tuple[str, str, str, str]] = [
    # --- as duas que o ticket nomeia ---
    #
    # A pasta responde «onde estou agora» e nao «fui cortado», porque muda
    # sozinha quando se ramifica. A *fixture* da bateria tem o sinal da pasta
    # **invertido** nas duas linhas, pelo que esta mutacao erra nos dois
    # sentidos; e o controlo estatico apanha-a tambem.
    ("pasta: a decisao passa a vir de .claude/skills/", ALVO,
     "    resposta = e_antepassado(raiz, origem, referencia)\n",
     '    resposta = (raiz / ".claude" / "skills" / "software-factory").is_dir()\n'),
    # O defeito real, e nao uma caricatura dele: capturar a saida do `merge-base`
    # nu e ler o vazio como «zero diferencas». E a forma que esteve a apagar sete
    # *worktrees* cujo trabalho a linha certa nao contem.
    ("codigo-de-saida: o merge-base deixa de ser lido pelo codigo", ALVO,
     '    resultado = _git(raiz, "merge-base", "--is-ancestor", commit, referencia)\n'
     "    if resultado.returncode == 0:\n"
     "        return True\n"
     "    if resultado.returncode == 1:\n"
     "        return False\n"
     "    return None\n",
     '    resultado = _git(raiz, "merge-base", commit, referencia)\n'
     "    return not resultado.stdout.strip()\n"),

    # --- a leitura do reflog, que e o que separa o ticket de um falso negativo ---
    ("coluna-nova: a origem passa a sair do valor novo (o defeito do `reflog show`)", ALVO,
     "    if entrada.velho != NULO:\n"
     '        return entrada.velho, "coluna do valor antigo da primeira entrada do reflog"\n'
     '    return entrada.novo, "coluna do valor novo da entrada de criacao do ramo"\n',
     '    return entrada.novo, "coluna do valor novo da entrada de criacao do ramo"\n'),
    ("coluna-antiga-sempre: a excepcao do OID nulo desaparece", ALVO,
     "    if entrada.velho != NULO:\n"
     '        return entrada.velho, "coluna do valor antigo da primeira entrada do reflog"\n'
     '    return entrada.novo, "coluna do valor novo da entrada de criacao do ramo"\n',
     '    return entrada.velho, "coluna do valor antigo da primeira entrada do reflog"\n'),
    ("ultima-entrada: o reflog passa a ler-se pelo fim (o presente)", ALVO,
     "            primeira = ficheiro.readline()\n",
     "            primeira = ficheiro.readlines()[-1]\n"),

    # --- o directorio de onde o reflog se le, que e o que faz isto valer num worktree ---
    ("git-dir: o reflog passa a procurar-se no directorio do worktree", ALVO,
     '    resultado = _git(raiz, "rev-parse", "--git-common-dir")\n',
     '    resultado = _git(raiz, "rev-parse", "--git-dir")\n'),

    # --- falha fechada ---
    ("falha-fechada: o «nao sei» passa a sair com zero", ALVO,
     "CODIGOS = {CONFORME: 0, RECUSADO: 1, DESCONHECIDO: 2}\n",
     "CODIGOS = {CONFORME: 0, RECUSADO: 1, DESCONHECIDO: 0}\n"),
    ("head-solto: um HEAD solto passa a contar como ramo", ALVO,
     '    if not nome or nome == "HEAD":\n        return None\n',
     "    if not nome:\n        return None\n"),
]

#: O que a copia leva. So `tools`: o `base.py` nao le mais nada do repositorio, e
#: a bateria constroi os repositorios de que precisa em directorios temporarios.
COPIAR = ("tools",)
IGNORAR = shutil.ignore_patterns("node_modules", "dist", "__pycache__", "*.egg-info")

#: A bateria que uma mutacao tem de por vermelha.
BATERIA = "test_base.py"


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
    copia = Path(tempfile.mkdtemp(prefix="kam180-mutacao-"))
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
    base = Path(tempfile.mkdtemp(prefix="kam180-base-"))
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
