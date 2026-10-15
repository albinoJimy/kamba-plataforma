"""Prova por mutacao dos dois leitores de YAML do KAM-148.

Desfaz cada correccao, uma de cada vez, numa copia do repositorio, e a *suite*
do leitor **tem de ficar vermelha**. Uma mutacao que sobreviva e um teste que
nao existe: foi assim que se descobriram tres buracos no corpus deste ticket (a
chave de topo repetida no ramo que abre uma lista, a *merge key* em estilo de
fluxo, e tres casos de quebra de linha ambigua que recusavam **pela regra
errada** — caiam na recusa do escalar nao citado com `: `).

## Porque nao esta no `db/mutacoes.py`

Esse corredor copia `db/` e `libs/py-core`, levanta um PostgreSQL por mutacao e
corre as *suites* de `db/`. **Nenhuma delas le por estes dois leitores**: o
`yamlreg` e lido pelo `canon_lint` e o `yamlsubset` pelo `secrets_inventory`,
duas *suites* de `tools/`. Em vez de alargar aquele corredor — que e trabalho
do KAM-142/KAM-143 e tem medicao propria — a prova faz-se aqui, com a mesma
ideia e sem Docker.

## Porque esta dentro de `tests/`

Nao e codigo de producao e nao e uma *suite*: o `unittest discover` so recolhe
`test_*.py`, e o `coverage-python` omite `*/tests/*` (`Makefile`), pelo que um
modulo que ninguem importa nao faz a cobertura descer. Corre-se a mao:

    python tools/canon_lint/tests/mutacoes_dos_leitores.py
    python tools/canon_lint/tests/mutacoes_dos_leitores.py yamlsubset   # so estas

Devolve 0 se todas as mutacoes forem apanhadas, 1 se alguma sobreviver ou se
alguma deixar de se aplicar (o alvo mudou de forma: `PROVA INVALIDA`).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]
REG = "tools/canon_lint/yamlreg.py"
SUB = "tools/secrets_inventory/yamlsubset.py"

#: A *suite* inteira do `canon_lint` le o conjunto documental todo e leva
#: minutos; a prova por mutacao destes dois leitores mede a *suite* do leitor.
#: As duas aspas tal como aparecem no codigo dos leitores, montadas por
#: `chr()` para o alvo nao ter uma escada de escapes.
ASPAS_NO_CODIGO = chr(34) + chr(92) + chr(34) + chr(39) + chr(34)
CHR_TAB = chr(92) + 't'
CHR_ASPA = chr(34)

PADRAO = {"canon_lint": "test_yamlreg.py", "secrets_inventory": "test_yamlsubset.py"}

#: `(nome, ficheiro, velho, novo, suite)`. O `velho` tem de aparecer **uma**
#: vez: se aparecer zero ou duas, a prova dessa mutacao nao vale e di-lo.
MUTACOES = [
    ("yamlreg: inteiro deixa de se converter", REG,
     '_INTEIRO = re.compile(r"^[-+]?(0|[1-9][0-9]*)$")',
     '_INTEIRO = re.compile(r"^(?!x)x$")', "canon_lint"),
    ("yamlreg: 'parece numero' deixa de recusar", REG,
     "    if _PARECE_NUMERO.match(texto):",
     "    if False:", "canon_lint"),
    ("yamlreg: ambiguos deixam de recusar", REG,
     '_AMBIGUOS = frozenset(\n    {\n        "True",',
     '_AMBIGUOS = frozenset(\n    {\n        "nao-existe-esta-palavra",', "canon_lint"),
    ("yamlreg: a chave volta ao conversor do valor", REG,
     '    bruta = bruta.strip()\n    if len(bruta) >= 2 and bruta[0] == bruta[-1] and bruta[0] in "\\"\'":\n'
     "        return bruta[1:-1]\n    return bruta",
     '    return str(_escalar(bruta, "chave"))', "canon_lint"),
    ("yamlreg: aspa por fechar volta a entrar no texto", REG,
     '        if fim == -1:\n            raise YamlIlegivel(f"{onde}: aspa {aspa} aberta e nao fechada ({texto!r})")',
     "        if fim == -1:\n            return texto", "canon_lint"),
    ("yamlreg: conteudo depois da aspa de fecho deixa de recusar", REG,
     "        if fim != len(texto) - 1:\n            resto = texto[fim + 1 :].strip()",
     "        if False:\n            resto = texto[fim + 1 :].strip()", "canon_lint"),
    ("yamlreg: escalar nao citado com ':' deixa de recusar", REG,
     '    if ": " in texto or texto.endswith(":"):',
     "    if False:", "canon_lint"),
    ("yamlreg: o inicio do escalar volta a ser qualquer aspa", REG,
     "        if fora_de_aspas and caractere in " + ASPAS_NO_CODIGO + " and (indice in aberturas or (em_fluxo and indice > inicio)):",
     "        if fora_de_aspas and caractere in " + ASPAS_NO_CODIGO + ":", "canon_lint"),
    ("yamlreg: lista aninhada deixa de recusar", REG,
     '            elif corpo == "-" or corpo.startswith("- "):',
     "            elif False:", "canon_lint"),
    ("yamlreg: caracteres de controlo deixam de recusar", REG,
     '_CONTROLO = re.compile(r"[\\x00-\\x08\\x0b\\x0c\\x0e-\\x1f\\x7f]")',
     '_CONTROLO = re.compile(r"(?!x)x")', "canon_lint"),
    ("yamlreg: quebras ambiguas deixam de recusar", REG,
     '_QUEBRAS_AMBIGUAS = {"\\x85',
     '_QUEBRAS_AMBIGUAS = {"nao-existe-este-caractere', "canon_lint"),
    ("yamlreg: o BOM volta a entrar no nome da chave", REG,
     '        texto = texto.lstrip("\\ufeff")',
     "        pass", "canon_lint"),
    ("yamlreg: o CR sozinho deixa de ser quebra de linha", REG,
     '        texto = texto.replace("\\r\\n", "\\n").replace("\\r", "\\n")',
     '        texto = texto.replace("\\r\\n", "\\n")', "canon_lint"),
    ("yamlreg: merge key volta a ser uma chave chamada '<<' (bloco)", REG,
     '            if chave == "<<":\n                # `<<: valor` e uma *merge key*.',
     "            if False:\n                # `<<: valor` e uma *merge key*.", "canon_lint"),
    ("yamlreg: merge key volta a ser uma chave chamada '<<' (fluxo)", REG,
     '                if chave == "<<":',
     "                if False:", "canon_lint"),
    ("yamlreg: chave vazia em fluxo deixa de recusar", REG,
     '                if bruta.strip() == "":',
     "                if False:", "canon_lint"),
    ("yamlsubset: `chave:valor` volta a ser um mapa", SUB,
     ":(?=[ " + CHR_TAB + "]|$)(?P<resto>.*)$" + CHR_ASPA,
     ":(?P<resto>.*)$" + CHR_ASPA, "secrets_inventory"),
    ("yamlsubset: chave de topo repetida volta a calar a primeira (lista)", SUB,
     '            if chave in raiz:\n'
     '                raise YamlSubsetError(f"{onde}: chave repetida no mapa de topo ({chave})")\n'
     "            lista_actual = []",
     "            lista_actual = []", "secrets_inventory"),
    ("yamlsubset: chave de topo repetida volta a calar a primeira (valor)", SUB,
     '            if chave in raiz:\n'
     '                raise YamlSubsetError(f"{onde}: chave repetida no mapa de topo ({chave})")\n'
     "            raiz[chave] = _valor(valor, onde)",
     "            raiz[chave] = _valor(valor, onde)", "secrets_inventory"),
    ("yamlsubset: a lista de fluxo volta ao split(',')", SUB,
     "    partes = _partes_do_fluxo(interior, onde)",
     '    partes = interior.split(",")', "secrets_inventory"),
    ("yamlsubset: inteiro volta ao int()", SUB,
     "    if _INTEIRO.match(texto):\n        return int(texto)",
     "    try:\n        return int(texto)\n    except ValueError:\n        pass\n"
     "    if False:\n        return int(texto)", "secrets_inventory"),
    ("yamlsubset: ambiguos deixam de recusar", SUB,
     '_AMBIGUOS = frozenset(\n    {\n        "True",',
     '_AMBIGUOS = frozenset(\n    {\n        "nao-existe-esta-palavra",', "secrets_inventory"),
    ("yamlsubset: 'parece numero' deixa de recusar", SUB,
     "    if _PARECE_NUMERO.match(texto):",
     "    if False:", "secrets_inventory"),
    ("yamlsubset: aspa por fechar volta a entrar no texto", SUB,
     '        if fim == -1:\n            raise YamlSubsetError(f"{onde}: aspa {aspa} aberta e nao fechada ({texto!r})")',
     "        if fim == -1:\n            return texto", "secrets_inventory"),
    ("yamlsubset: o inicio do escalar volta a ser qualquer aspa", SUB,
     "        if fora_de_aspas and caractere in " + ASPAS_NO_CODIGO + " and (indice in aberturas or (em_fluxo and indice > inicio)):",
     "        if fora_de_aspas and caractere in " + ASPAS_NO_CODIGO + ":", "secrets_inventory"),
    ("yamlsubset: o BOM volta a entrar no nome da chave", SUB,
     '    texto = texto.lstrip("\\ufeff")',
     "    pass", "secrets_inventory"),
    ("yamlsubset: quebras ambiguas deixam de recusar", SUB,
     '_QUEBRAS_AMBIGUAS = {"\\x85',
     '_QUEBRAS_AMBIGUAS = {"nao-existe-este-caractere', "secrets_inventory"),
    ("yamlsubset: caracteres de controlo deixam de recusar", SUB,
     "        if achado_controlo:",
     "        if False:", "secrets_inventory"),
    ("yamlsubset: a tabulacao deixa de recusar", SUB,
     '        if "\\t" in linha_bruta:',
     "        if False:", "secrets_inventory"),
    ("yamlsubset: item de lista volta a aceitar o que nao e 'chave: valor'", SUB,
     '            if achado is None or achado.group("resto").strip() == "":\n'
     '                raise YamlSubsetError(f"{onde}: item de lista tem de ser \'chave: valor\'")',
     '            if achado is None:\n                achado = _CHAVE.match(corpo + ": x")', "secrets_inventory"),

    # --- as regras que a revisao adversarial trouxe (ANALISE-13 §4) -------
    ("yamlreg: o limite de profundidade do bloco desaparece", REG,
     "        if profundidade > _PROFUNDIDADE_MAXIMA:",
     "        if False:", "canon_lint"),
    ("yamlreg: o limite de profundidade do fluxo desaparece", REG,
     "        if self.profundidade > _PROFUNDIDADE_MAXIMA:",
     "        if False:", "canon_lint"),
    ("yamlreg: os indicadores de fluxo deixam de recusar", REG,
     '    "]": "indicador de fluxo",',
     '    "nao-existe-este-indicador": "indicador de fluxo",', "canon_lint"),
    ("yamlreg: a chave explicita deixa de recusar", REG,
     '    if texto == "?" or texto.startswith("? "):',
     "    if False:", "canon_lint"),
    ("yamlreg: os indicadores voltam a poder comecar um nome de chave", REG,
     r"""[^\s"'{}\[\],:#&*!|>%@`?]""",
     r"""[^\s"'{}\[\],:#&*!|>]""", "canon_lint"),
    ("yamlreg: a recusa nomeada do indicador em posicao de chave desaparece", REG,
     "                if conteudo[:1] in _PROIBIDOS:",
     "                if False:", "canon_lint"),
    ("yamlreg: a aspa deixa de abrir no nome da chave", REG,
     "    aberturas = {inicio, inicio_da_chave}",
     "    aberturas = {inicio}", "canon_lint"),
    ("yamlreg: o item de lista com chave citada volta a nao ser mapa", REG,
     '            elif corpo[:1] not in ("{", "[") and _CHAVE.match(corpo):',
     '            elif corpo[:1] not in ("{", "[", \'"\', "\'") and _CHAVE.match(corpo):',
     "canon_lint"),
    ("yamlsubset: a classe de chave volta a recusar acentos", SUB,
     r"""(?P<chave>\"[^\"]+\"|'[^']+'|[^\s\"'{}\[\],:#&*!|>%@`?][^:#]*?)\s*:""",
     r"""(?P<chave>[A-Za-z_][A-Za-z0-9_.-]*|\"[^\"]+\"|'[^']+'):""", "secrets_inventory"),
    ("yamlsubset: a merge key volta a ser uma chave chamada '<<'", SUB,
     '    if bruta == "<<":',
     "    if False:", "secrets_inventory"),
    ("yamlsubset: os indicadores de fluxo deixam de recusar", SUB,
     '    "]": "indicador de fluxo",',
     '    "nao-existe-este-indicador": "indicador de fluxo",', "secrets_inventory"),
    ("yamlsubset: a chave explicita deixa de recusar", SUB,
     '    if texto == "?" or texto.startswith("? "):',
     "    if False:", "secrets_inventory"),
    ("yamlsubset: a chave sem valor volta a ser uma lista vazia", SUB,
     "            chave_da_lista = chave\n            raiz[chave] = None",
     "            chave_da_lista = None\n            raiz[chave] = lista_actual", "secrets_inventory"),
    ("yamlsubset: o aninhamento volta a ser visto antes das aspas", SUB,
     "    partes = _partes_do_fluxo(interior, onde)",
     '    if "[" in interior or "]" in interior:\n'
     '        raise YamlSubsetError(f"{onde}: lista de listas nao suportada")\n'
     "    partes = _partes_do_fluxo(interior, onde)", "secrets_inventory"),
    ("yamlsubset: a aspa deixa de abrir no nome da chave", SUB,
     "    aberturas = {inicio, inicio_da_chave}",
     "    aberturas = {inicio}", "secrets_inventory"),
    ("yamlsubset: a recusa nomeada do indicador em posicao de chave desaparece", SUB,
     "            if corpo[:1] in _PROIBIDOS:",
     "            if False:", "secrets_inventory"),
]

#: O que a copia leva. Os dois leitores leem ficheiros do repositorio, e os
#: testes de equivalencia descobrem o corpus por *glob*.
_COPIAR = ("tools", "ops", "registry", "specs", "canon", "ci", "docs", "db")


def _suite(copia: Path, nome: str) -> tuple[int, str]:
    processo = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", f"tools/{nome}/tests",
         "-t", "tools", "-p", PADRAO[nome]],
        cwd=copia, capture_output=True, text=True, errors="replace",
    )
    return processo.returncode, (processo.stdout + processo.stderr)[-500:]


def main(argumentos: list[str]) -> int:
    filtro = argumentos[0] if argumentos else ""
    apanhadas: list[str] = []
    sobreviventes: list[tuple[str, str]] = []
    invalidas: list[tuple[str, str]] = []
    with tempfile.TemporaryDirectory() as pasta:
        copia = Path(pasta) / "copia"
        for nome in _COPIAR:
            origem = RAIZ / nome
            if origem.is_dir():
                shutil.copytree(origem, copia / nome,
                                ignore=shutil.ignore_patterns("__pycache__", "node_modules"))
        for nome in ("canon_lint", "secrets_inventory"):
            codigo, saida = _suite(copia, nome)
            print(f"linha de base {nome}: {'verde' if codigo == 0 else 'VERMELHA'}")
            if codigo != 0:
                print(saida)
                print("  a prova nao vale sobre uma linha de base vermelha")
                return 2
        for nome, ficheiro, velho, novo, qual in MUTACOES:
            if filtro and filtro not in nome:
                continue
            caminho = copia / ficheiro
            original = caminho.read_text(encoding="utf-8")
            if original.count(velho) != 1:
                invalidas.append((nome, f"o alvo aparece {original.count(velho)} vezes"))
                print(f"  PROVA INVALIDA  {nome}")
                continue
            caminho.write_text(original.replace(velho, novo), encoding="utf-8", newline="\n")
            try:
                codigo, saida = _suite(copia, qual)
            finally:
                caminho.write_text(original, encoding="utf-8", newline="\n")
            if codigo == 0:
                sobreviventes.append((nome, saida))
                print(f"  SOBREVIVEU      {nome}")
            else:
                apanhadas.append(nome)
                print(f"  apanhada        {nome}")
    print(f"\n{len(apanhadas)} apanhadas, {len(sobreviventes)} sobreviventes, "
          f"{len(invalidas)} provas invalidas")
    for nome, porque in invalidas:
        print(f"  invalida: {nome} ({porque})")
    for nome, saida in sobreviventes:
        print(f"  sobreviveu: {nome}\n{saida}")
    return 1 if sobreviventes or invalidas else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
