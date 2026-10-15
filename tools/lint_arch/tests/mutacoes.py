"""Prova por mutacao do gate 4 — a medicao do ambito inteiro (KAM-132).

    python tools/lint_arch/tests/mutacoes.py [filtro]
    python tools/lint_arch/tests/mutacoes.py --aplicaveis

Um teste que passa nao prova que morde. Isto prova: copia o codigo para um
directorio temporario **fora do repositorio**, confirma que a linha de base
esta verde, e aplica **uma** alteracao deliberadamente errada de cada vez — o
ficheiro sem medicao deixa de entrar, os `excluidos` deixam de valer na
injeccao, o `--test-coverage-include` deixa de chegar ao `node --test` — e exige
que as baterias fiquem vermelhas. O repositorio nao e tocado.

**Porque nao vive em `db/mutacoes.py`.** Aquele e o arreio dos gates de base de
dados: copia `db/`, `libs/py-core/`, `ci/` e `packages/core-ts/` e corre
`db/gate_bd.py` contra um PostgreSQL descartavel. Nao exercita o
`tools/coverage_gate.py` nem o `Makefile`, pelo que uma mutacao do gate 4 posta
la sobrevivia **por construcao** — uma prova que da por provado o que nunca
correu. Vive onde vive o codigo, como a do *logger*
(`tools/log_policy/tests/mutacoes.py`) e a da cadeia de fornecimento
(`tools/supply_chain/canario.py`).

Cada mutacao leva a sua propria copia e correm **em paralelo**
(`KAMBA_MUTACOES_PARALELO`, por omissao 8). Sao segundos cada: nao precisam de
Docker, de rede nem de base de dados.

`--aplicaveis` confirma, sem correr teste nenhum, que o texto de todas as
mutacoes existe exactamente uma vez no ficheiro alvo. Uma mutacao que deixou de
se aplicar e uma prova que deixou de provar.

Nao faz parte de nenhum gate. Corre-se quando se mexe no `coverage_gate`, nos
limiares ou no alvo `coverage-node`, e o resultado registra-se na analise do
ticket. Uma mutacao que **sobreviva** e um teste em falta.

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

GATE = "tools/coverage_gate.py"
LIMIARES = "ci/thresholds.yaml"
MAKEFILE = "Makefile"

#: (nome, ficheiro, texto antigo, texto novo). O nome diz o defeito que a
#: mutacao introduz, nao a linha que troca.
MUTACOES: list[tuple[str, str, str, str]] = [
    # --- a injeccao, que e o que este ticket entrega ---
    ("gate4: o ficheiro sem medicao nao entra no denominador", GATE,
     "            medicoes[caminho] = Medicao(\n"
     "                caminho,\n"
     "                linhas_encontradas=linhas_do_ficheiro(raiz / caminho),\n"
     "                linhas_cobertas=0,\n"
     "            )\n",
     ""),
    ("gate4: o ficheiro sem medicao entra como se estivesse coberto", GATE,
     "                linhas_cobertas=0,\n",
     "                linhas_cobertas=linhas_do_ficheiro(raiz / caminho),\n"),
    ("gate4: quem entrou a 0% nao sai pelo nome", GATE,
     "        for caminho in injectados:\n            print(f\"    . {caminho}\")\n",
     ""),
    ("gate4: a injeccao fica atras de uma condicao sempre falsa", GATE,
     "    if not argumentos.sem_universo:\n", "    if False:\n"),

    # --- o universo lido do disco ---
    ("universo: os excluidos deixam de valer na injeccao", GATE,
     "        if not limiares.esta_excluido(c) and limiares.classificar(c) is not None",
     "        if limiares.classificar(c) is not None"),
    ("universo: um ficheiro sem estrato passa a ser injectado", GATE,
     "        if not limiares.esta_excluido(c) and limiares.classificar(c) is not None",
     "        if not limiares.esta_excluido(c)"),
    ("universo: as pastas com ponto a cabeca contam como codigo", GATE,
     "                if s not in PASTAS_FORA_DO_UNIVERSO and not s.startswith(\".\")\n",
     "                if s not in PASTAS_FORA_DO_UNIVERSO\n"),
    ("universo: percorre as dependencias de terceiros", GATE,
     'PASTAS_FORA_DO_UNIVERSO = frozenset({"__pycache__", "dist", "node_modules"})',
     "PASTAS_FORA_DO_UNIVERSO = frozenset()"),
    ("universo: tambem conta ficheiros que nenhum medidor le", GATE,
     '    ".ts", ".mts", ".cts", ".tsx", ".js", ".mjs", ".cjs", ".jsx",',
     '    ".ts", ".md",'),
    ("universo: volta a deixar fugir tudo o que nao seja .ts", GATE,
     '    ".ts", ".mts", ".cts", ".tsx", ".js", ".mjs", ".cjs", ".jsx",',
     '    ".ts",'),
    ("universo: volta a percorrer a arvore inteira em vez das raizes", GATE,
     "    for nome_da_raiz in raizes_do_universo(limiares):\n"
     "        base = raiz / nome_da_raiz\n",
     "    for nome_da_raiz in (\".\",):\n"
     "        base = raiz / nome_da_raiz\n"),
    ("universo: sem raiz literal mede zero em silencio", GATE,
     "        raise ConfiguracaoInvalida(\n"
     '            "ci/thresholds.yaml: nenhum padrao de estrato comeca por um nome de "\n'
     '            "pasta literal, pelo que nao ha por onde procurar o universo. Pelo "\n'
     '            "menos um estrato precisa de um padrao como `services/*/src/**`."\n'
     "        )\n",
     "        return ()\n"),

    # --- o denominador de um ficheiro sem medicao ---
    ("linhas: volta a contar pelos separadores do splitlines", GATE,
     "    return len(_TERMINADORES_DE_LINHA.split(texto))",
     "    return len(texto.splitlines())"),
    ("linhas: o ultimo terminador abre uma linha nova", GATE,
     r'    if texto[-1] in "\n\r\u2028\u2029":' "\n" "        texto = texto[:-1]\n",
     ""),

    # --- a lista do --test-coverage-exclude ---
    ("exclusoes: um pacote sem ficheiros no ambito deixa de ser erro", GATE,
     '"PACOTES_NODE",\n                file=sys.stderr,\n            )\n            return 2',
     '"PACOTES_NODE",\n                file=sys.stderr,\n            )\n            return 0'),
    ("exclusoes: os caminhos saem relativos a raiz e nao ao pacote", GATE,
     "            c[len(prefixo) :] for c in excluidos_no_disco(raiz, limiares, pacote)",
     "            c for c in excluidos_no_disco(raiz, limiares, pacote)"),
    ("exclusoes: um caminho com espaco passa em silencio", GATE,
     "        if com_espaco:\n", "        if False:\n"),
    ("exclusoes: passa o ambito em vez do que esta excluido", GATE,
     "        if c.startswith(prefixo) and limiares.esta_excluido(c)",
     "        if c.startswith(prefixo) and not limiares.esta_excluido(c)"),

    # --- a cablagem do alvo ---
    ("cablagem: o node --test deixa de receber a lista", MAKEFILE,
     "	  if (cd \"$$pacote\" && node --test --experimental-test-coverage $$excluir \\\n",
     "	  if (cd \"$$pacote\" && node --test --experimental-test-coverage \\\n"),
    ("cablagem: a lista passa a ser escrita a mao no Makefile", MAKEFILE,
     "	  \"$$PY\" tools/coverage_gate.py --root $(ROOT) --exclusoes-node \"$$pacote\" >\"$$lista\"; \\\n",
     "	  echo \"src/server.ts\" >\"$$lista\"; \\\n"),
    ("cablagem: volta a filtrar pelo ambito em vez de excluir", MAKEFILE,
     "	  excluir=$$(sed \"s|^|--test-coverage-exclude=|\" \"$$lista\" | tr \"\\n\" \" \"); \\\n",
     "	  excluir=$$(sed \"s|^|--test-coverage-include=|\" \"$$lista\" | tr \"\\n\" \" \"); \\\n"),

    # --- a cablagem do lado Python (KAM-151) ---
    #
    # Do lado Node o universo garante-se por injeccao, e as mutacoes acima
    # provam-na. Do lado Python garante-se por **cablagem**: um `--source=` por
    # pasta de `.py` do ambito. Estas quatro provam que essa cablagem morde —
    # sem elas, a propriedade que o KAM-151 entrega estava provada por uma
    # execucao pontual e nao por oraculo permanente.
    ("cablagem: services/agr/src volta a nao ser medido", MAKEFILE,
     "	@$(VENV_PYTHON) -m coverage run --branch --source=services/agr/src \\\n",
     "	@$(VENV_PYTHON) -m coverage run --branch --source=libs/py-core/src \\\n"),
    ("cablagem: o LCOV do AGR sai do glob que o gate le", MAKEFILE,
     "	@$(VENV_PYTHON) -m coverage lcov -o ci/coverage/python-services-agr.lcov --quiet\n",
     "	@$(VENV_PYTHON) -m coverage lcov -o ci/coverage/agr.dat --quiet\n"),
    ("cablagem: o LCOV do AGR ganha um nome que nao resolve para pasta", MAKEFILE,
     "	@$(VENV_PYTHON) -m coverage lcov -o ci/coverage/python-services-agr.lcov --quiet\n",
     "	@$(VENV_PYTHON) -m coverage lcov -o ci/coverage/python-agr.lcov --quiet\n"),
    ("cablagem: o run do AGR apaga os dados do libs antes do seu LCOV", MAKEFILE,
     "	@$(VENV_PYTHON) -m coverage lcov -o ci/coverage/python-libs.lcov --quiet\n"
     "	@# E a suite do AGR",
     "	@# E a suite do AGR"),

    # --- os limiares, que decidem quem e medido ---
    ("limiares: o estrato restante baixa de 75 para 50", LIMIARES,
     "    minimo_linhas: 75", "    minimo_linhas: 50"),
    ("limiares: o servico de identidade deixa de estar excluido", LIMIARES,
     '  - "packages/core-ts/src/identity/contactos.ts"\n', ""),
    ("limiares: os pontos de entrada deixam de estar excluidos", LIMIARES,
     '  - "services/*/src/server.ts"\n', ""),
]

#: O que a copia leva. `packages`, `services` e `libs` entram porque a bateria
#: le o **ambito real do repositorio** e nao so arvores inventadas.
COPIAR = ("tools", "packages", "services", "libs", LIMIARES, MAKEFILE)
IGNORAR = shutil.ignore_patterns("node_modules", "dist", "__pycache__", "*.egg-info")

#: As duas baterias que uma mutacao tem de por vermelhas.
BATERIAS = ("test_coverage_gate.py", "test_makefile.py")


def _copiar(destino: Path) -> None:
    for relativo in COPIAR:
        origem, alvo = RAIZ / relativo, destino / relativo
        alvo.parent.mkdir(parents=True, exist_ok=True)
        if origem.is_dir():
            shutil.copytree(origem, alvo, ignore=IGNORAR)
        else:
            shutil.copy(origem, alvo)


def _passa(copia: Path) -> bool:
    """`True` se as duas baterias passarem na copia."""
    ambiente = dict(os.environ)
    ambiente["PYTHONPATH"] = str(copia / "tools")
    ambiente["PYTHONDONTWRITEBYTECODE"] = "1"
    for padrao in BATERIAS:
        resultado = subprocess.run(
            [
                sys.executable, "-m", "unittest", "discover",
                "-s", "lint_arch/tests", "-t", ".", "-p", padrao,
            ],
            cwd=copia / "tools",
            env=ambiente,
            capture_output=True,
        )
        if resultado.returncode != 0:
            return False
    return True


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
    copia = Path(tempfile.mkdtemp(prefix="kam132-mutacao-"))
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
    base = Path(tempfile.mkdtemp(prefix="kam132-base-"))
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
    # A ordem do relatorio e a da lista, nao a de chegada.
    sobreviventes = []
    for nome, _ficheiro, _velho, _novo in escolhidas:
        if resultados[nome]:
            print(f"  apanhada     {nome}")
        else:
            print(f"  SOBREVIVEU   {nome}")
            sobreviventes.append(nome)
    print(
        f"\n{len(escolhidas)} mutacoes: {len(escolhidas) - len(sobreviventes)} "
        f"apanhadas, {len(sobreviventes)} sobreviventes"
    )
    return 1 if sobreviventes else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
