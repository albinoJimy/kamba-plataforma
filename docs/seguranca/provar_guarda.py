"""Prova que a guarda nova morde — e que a antiga nao chegava as verificacoes.

Monta arvores temporarias (nao commitadas) e corre o validador contra cada uma:

  1. real      as fontes verdadeiras                  -> a guarda NAO dispara
  2. vazia     specs/INDICE.md semeado a nao bater    -> ERRO DE CONFIGURACAO
  3. piso      INDICE.md com so 3 linhas de KAM       -> ERRO DE CONFIGURACAO
  4. antigo    o assert de 138 contra a arvore real   -> AssertionError (o «antes»)

Uso, da raiz do repositorio:

    python -I docs/seguranca/provar_guarda.py .

O caso 4 e opcional e precisa de uma copia do validador anterior ao KAM-149,
que nao vive nesta arvore (ver a docstring do `validar.py`):

    python -I docs/seguranca/provar_guarda.py . <copia-do-validador-antigo>

**Nao esta no CI**, como o `validar.py`: e a lacuna L-20, que precisa de ticket
proprio por tocar em `tools/` e `.github/` e por um portao novo entrar nos
*required checks*. Enquanto isso, corre-se a mao e a saida fica na evidencia.

Nenhuma fonte semeada e escrita no repositorio: tudo acontece numa copia dentro
de uma pasta temporaria, que desaparece no fim.
"""
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RAIZ = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else ".")
ANTIGO = os.path.abspath(sys.argv[2]) if len(sys.argv) > 2 else None
PY = sys.executable

#: O minimo que o validador le. Copiado para uma arvore temporaria onde se pode
#: semear uma fonte sem tocar no repositorio.
PRECISA = [
    "docs/seguranca",
    "docs/analises",
    "docs/runbooks",
    "docs/tecnica",
    "specs",
]


def montar(destino):
    for rel in PRECISA:
        origem = os.path.join(RAIZ, rel)
        if os.path.isdir(origem):
            shutil.copytree(origem, os.path.join(destino, rel.replace("/", os.sep)))


def correr(validador, raiz):
    p = subprocess.run(
        [PY, "-I", validador, raiz], capture_output=True, text=True, encoding="utf-8",
        errors="replace",
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def linhas_de_canon(saida):
    return [
        l.strip()
        for l in saida.splitlines()
        if "canon:" in l or "ERROS DE CONFIGURACAO" in l or "RESUMO" in l
    ]


VALIDADOR = os.path.join(RAIZ, "docs", "seguranca", "validar.py")

print("=" * 78)
print("CASO 1 — fontes reais: a guarda nao dispara")
print("=" * 78)
rc, saida = correr(VALIDADOR, RAIZ)
canon = [l for l in saida.splitlines() if "canon lido" in l]
print("codigo de saida:", rc)
print("  ", canon[0].strip() if canon else "(sem linha de canon)")
disparou = [l for l in saida.splitlines() if "canon:" in l]
print("  guarda do canon disparou:", bool(disparou))
assert not disparou, "a guarda disparou com as fontes reais: " + str(disparou)
print("  OK: com as fontes reais a guarda fica calada, e o relatorio sai.")

for nome, semente, descricao in (
    (
        "vazia",
        "",
        "specs/INDICE.md sem nenhuma linha `| KAM-NNN |` -> conjunto VAZIO",
    ),
    (
        "piso",
        "| KAM-001 | a |\n| KAM-002 | b |\n| KAM-003 | c |\n",
        "specs/INDICE.md com 3 linhas -> abaixo do piso de 10",
    ),
):
    print()
    print("=" * 78)
    print("CASO %s — %s" % (nome, descricao))
    print("=" * 78)
    with tempfile.TemporaryDirectory() as tmp:
        montar(tmp)
        shutil.copy2(VALIDADOR, os.path.join(tmp, "docs", "seguranca", "validar.py"))
        alvo = os.path.join(tmp, "specs", "INDICE.md")
        bruto = io.open(alvo, encoding="utf-8").read()
        # Semeia: retira as linhas de tabela do KAM e, no caso `piso`, poe tres.
        semeado = re.sub(r"^\| KAM-\d{3} \|.*$", "", bruto, flags=re.M) + semente
        io.open(alvo, "w", encoding="utf-8", newline="\n").write(semeado)
        n = len(re.findall(r"^\| (KAM-\d{3}) \|", semeado, re.M))
        print("  semeado: o INDICE.md da copia rende %d linhas de KAM" % n)
        rc, saida = correr(os.path.join(tmp, "docs", "seguranca", "validar.py"), tmp)
        print("  codigo de saida:", rc)
        for l in linhas_de_canon(saida):
            print("    ", l[:150])
        assert rc == 1, "esperava 1, veio %d" % rc
        assert "Traceback" not in saida, "houve traceback:\n" + saida[-800:]
        assert any("canon:" in l for l in saida.splitlines()), (
            "a guarda NAO disparou com a fonte semeada:\n" + saida[-800:]
        )
        assert "OK: 0 erros" not in saida, "deu «0 erros» com a fonte semeada"
        print("  OK: erro de configuracao com mensagem, sem traceback, sem «0 erros».")

if ANTIGO:
    print()
    print("=" * 78)
    print("CASO antigo — o assert de 138 contra esta arvore: o «antes»")
    print("=" * 78)
    with tempfile.TemporaryDirectory() as tmp:
        copia = os.path.join(tmp, "validar_antigo.py")
        shutil.copy2(ANTIGO, copia)
        rc, saida = correr(copia, RAIZ)
        print("  codigo de saida:", rc)
        for l in saida.splitlines():
            if "AssertionError" in l or "assert len(KAM)" in l:
                print("    ", l.strip()[:150])
        print("  tem traceback:", "Traceback" in saida)
        print("  chegou a imprimir alguma familia (MATRIZ/STRIDE/DPIA/DOCS):",
              any(saida.startswith(f) or ("\n" + f) in saida
                  for f in ("MATRIZ", "STRIDE", "DPIA", "DOCS")))

print()
print("TODAS AS ASSERCOES PASSARAM.")
