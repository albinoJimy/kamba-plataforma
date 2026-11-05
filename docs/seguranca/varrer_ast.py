"""Varrimento por AST: contagens fixadas no CODIGO, nao no texto.

O varrimento por expressao regular ve tambem docstrings e comentarios, e um
ficheiro que *explique* o defeito aparece como se o tivesse. Este le a arvore
sintactica: so compara o que o interpretador executa.

Procura comparacoes entre `len(...)` (ou `.count(...)`) e um literal inteiro de
dois ou mais digitos, e atribuicoes de constantes com nome de contagem.
"""
import ast
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

NOMES_DE_CONTAGEM = ("TOTAL", "ESPERADO", "N_", "NUM_", "CONTAGEM")


def chamadas_de_tamanho(no):
    return (
        isinstance(no, ast.Call)
        and (
            (isinstance(no.func, ast.Name) and no.func.id == "len")
            or (isinstance(no.func, ast.Attribute) and no.func.attr == "count")
        )
    )


def literal_grande(no):
    return isinstance(no, ast.Constant) and isinstance(no.value, int) and no.value >= 10


achados = []
alvos = []
for arg in sys.argv[1:]:
    p = Path(arg)
    alvos.extend(sorted(p.rglob("*.py")) if p.is_dir() else [p])

for f in alvos:
    arvore = ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
    for no in ast.walk(arvore):
        if isinstance(no, ast.Compare):
            lados = [no.left] + list(no.comparators)
            tem_tamanho = any(chamadas_de_tamanho(x) for x in lados)
            tem_literal = any(literal_grande(x) for x in lados)
            if tem_tamanho and tem_literal:
                achados.append((f, no.lineno, ast.unparse(no)[:120]))
        if isinstance(no, ast.Assign):
            for alvo in no.targets:
                if (
                    isinstance(alvo, ast.Name)
                    and any(alvo.id.startswith(n) for n in NOMES_DE_CONTAGEM)
                    and literal_grande(no.value)
                ):
                    achados.append((f, no.lineno, ast.unparse(no)[:120]))

for f, n, txt in achados:
    print(f"{f.as_posix()}:{n}: {txt}")
print(f"--- ficheiros varridos: {len(alvos)}; contagens fixadas no CODIGO: {len(achados)}")

# E, para contraste, todos os `assert` que o codigo executa.
print()
for f in alvos:
    arvore = ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
    for no in ast.walk(arvore):
        if isinstance(no, ast.Assert):
            print(f"(assert) {f.as_posix()}:{no.lineno}: {ast.unparse(no.test)[:110]}")
