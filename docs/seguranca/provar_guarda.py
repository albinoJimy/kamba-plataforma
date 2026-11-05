"""Prova que as guardas do `validar.py` mordem — e que a antiga nao chegava as
verificacoes.

Monta arvores temporarias (nada e escrito no repositorio), semeia uma fonte, e
corre o validador contra cada uma. Cada caso diz o que **espera**, e o `scrip`
falha se a expectativa nao se cumprir — e um teste, nao uma demonstracao.

Uso, da raiz do repositorio:

    python -I docs/seguranca/provar_guarda.py .

O ultimo caso e opcional e precisa de uma copia do validador anterior ao
KAM-149, que nao vive nesta arvore (ver a docstring do `validar.py`):

    python -I docs/seguranca/provar_guarda.py . <copia-do-validador-antigo>

**Nao esta no CI**, como o `validar.py`: e a lacuna L-20, que precisa de ticket
proprio por tocar em `tools/` e `.github/` e por um portao novo entrar nos
*required checks*. Enquanto isso, corre-se a mao e a saida fica na evidencia.

## O que isto NAO prova, e esta medido

Um piso mede «a regex devolveu pouco», nao «a regex devolveu a coisa errada».
O caso `deriva_calada` abaixo demonstra-o: com dez entradas **falsas** no
`INDICE.md`, a guarda fica em silencio e o relatorio fica indistinguivel do caso
vazio. E uma limitacao declarada, nao um esquecimento — apanhar a segunda exigia
conferir os identificadores contra outra fonte, e nao ha segunda fonte.
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
VALIDADOR = os.path.join(RAIZ, "docs", "seguranca", "validar.py")

#: O minimo que o validador le. Copiado para uma arvore temporaria onde se pode
#: semear uma fonte sem tocar no repositorio.
PRECISA = ("docs/seguranca", "docs/analises", "docs/runbooks", "docs/tecnica", "specs")

INDICE = "specs/INDICE.md"
ARQ = "docs/tecnica/00_Arquitectura_Solucao.md"


def montar(destino):
    for rel in PRECISA:
        origem = os.path.join(RAIZ, rel)
        if os.path.isdir(origem):
            shutil.copytree(origem, os.path.join(destino, rel.replace("/", os.sep)))
    shutil.copy2(VALIDADOR, os.path.join(destino, "docs", "seguranca", "validar.py"))


def correr(validador, raiz):
    p = subprocess.run(
        [PY, "-I", validador, raiz], capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def apagar_linhas(caminho, padrao, juntar=""):
    bruto = io.open(caminho, encoding="utf-8").read()
    novo = re.sub(padrao, "", bruto, flags=re.M) + juntar
    io.open(caminho, "w", encoding="utf-8", newline="\n").write(novo)


# --------------------------------------------------------------------- casos
#
# Cada caso: (nome, descricao, semear(tmp), sinal_esperado)
# `sinal_esperado` e a cadeia que **tem** de aparecer nos erros de configuracao.
# `None` significa «nenhuma guarda deve disparar».

def _vazio_kam(tmp):
    apagar_linhas(os.path.join(tmp, "specs", "INDICE.md"), r"^\| KAM-\d{3} \|.*$")


def _piso_kam(tmp):
    apagar_linhas(
        os.path.join(tmp, "specs", "INDICE.md"), r"^\| KAM-\d{3} \|.*$",
        "| KAM-001 | a |\n| KAM-002 | b |\n| KAM-003 | c |\n",
    )


def _vazio_adr(tmp):
    apagar_linhas(os.path.join(tmp, *ARQ.split("/")), r"^\| \*{0,2}ADR-\d{3}\*{0,2} \|.*$")


def _piso_adr(tmp):
    apagar_linhas(
        os.path.join(tmp, *ARQ.split("/")), r"^\| \*{0,2}ADR-\d{3}\*{0,2} \|.*$",
        "| ADR-001 | a |\n| ADR-002 | b |\n| ADR-003 | c |\n| ADR-004 | d |\n",
    )


def _vazio_dec(tmp):
    apagar_linhas(os.path.join(tmp, *ARQ.split("/")), r"^\| D\d{1,2} \|.*$")


def _indice_ausente(tmp):
    os.remove(os.path.join(tmp, "specs", "INDICE.md"))


def _arq_ausente(tmp):
    os.remove(os.path.join(tmp, *ARQ.split("/")))


def _md_nao_utf8(tmp):
    alvo = os.path.join(tmp, "docs", "seguranca", "zz_nao_utf8.md")
    io.open(alvo, "wb").write(b"# t\xed\xf4ulo em cp1252\n\n## Controlo de vers\xf5es\n")


def _md_que_e_pasta(tmp):
    os.mkdir(os.path.join(tmp, "docs", "seguranca", "zz_pasta.md"))


def _deriva_calada(tmp):
    # Dez entradas FALSAS: a regex bate, o piso passa, e a guarda fica muda.
    apagar_linhas(
        os.path.join(tmp, "specs", "INDICE.md"), r"^\| KAM-\d{3} \|.*$",
        "".join("| KAM-%03d | inventado |\n" % n for n in range(901, 911)),
    )


CASOS = (
    ("vazio_kam", "INDICE.md sem nenhuma linha | KAM-NNN | -> conjunto VAZIO",
     _vazio_kam, "o conjunto KAM veio VAZIO"),
    ("piso_kam", "INDICE.md com 3 linhas -> abaixo do piso",
     _piso_kam, "o conjunto KAM tem 3 entradas, abaixo do piso"),
    ("vazio_adr", "00_Arquitectura sem ADR-NNN -> conjunto VAZIO",
     _vazio_adr, "o conjunto ADR veio VAZIO"),
    ("piso_adr", "00_Arquitectura com 4 ADR -> abaixo do piso",
     _piso_adr, "o conjunto ADR tem 4 entradas, abaixo do piso"),
    ("vazio_dec", "00_Arquitectura sem DN -> conjunto VAZIO",
     _vazio_dec, "o conjunto DEC veio VAZIO"),
    ("indice_ausente", "specs/INDICE.md APAGADO -> erro de configuracao, nao FileNotFoundError",
     _indice_ausente, "a fonte specs/INDICE.md nao existe"),
    ("arq_ausente", "00_Arquitectura APAGADO -> erro de configuracao",
     _arq_ausente, "nao existe"),
    ("md_nao_utf8", "um .md que nao e UTF-8 -> erro de configuracao, nao UnicodeDecodeError",
     _md_nao_utf8, "nao e UTF-8"),
)

#: Casos cujo desfecho correcto e **nao haver nada a reportar**: a entrada
#: patologica e ignorada por construcao, e a prova e o programa correr inteiro.
IGNORADOS = (
    # Uma pasta chamada `zz_pasta.md` dava `PermissionError` no `os.listdir` do
    # original (achado 3 da revisao adversarial, caso 13). Com a travessia por
    # `os.walk`, que rende apenas ficheiros, ela nao entra nos alvos — nem erro,
    # nem excepcao, nem dispensa a declarar.
    ("md_que_e_pasta", "um «.md» que e uma pasta -> ignorado pela travessia", _md_que_e_pasta),
)

#: Casos cujo valor e mostrar que a guarda **nao** chega la. Falham se ela
#: disparar, porque isso significava que a limitacao declarada deixou de o ser.
LIMITACOES = (
    ("deriva_calada", "INDICE.md com 10 entradas FALSAS -> o piso passa e a guarda cala-se",
     _deriva_calada),
)

falhas = []


def confere(nome, condicao, porque):
    if not condicao:
        falhas.append("%s: %s" % (nome, porque))
        print("  FALHOU:", porque)
        return False
    return True


print("=" * 78)
print("CONTROLO — fontes reais: nenhuma guarda do canon dispara")
print("=" * 78)
rc, saida = correr(VALIDADOR, RAIZ)
disparou = [l for l in saida.splitlines() if "canon:" in l]
print("  codigo de saida:", rc)
for l in saida.splitlines():
    if "canon lido" in l:
        print("  ", l.strip())
confere("controlo", not disparou, "a guarda disparou com as fontes reais: %s" % disparou)
confere("controlo", "Traceback" not in saida, "traceback com as fontes reais")
if not disparou:
    print("  OK: com as fontes reais a guarda fica calada, e o relatorio sai.")

for nome, descricao, semear, sinal in CASOS:
    print()
    print("=" * 78)
    print("CASO %s — %s" % (nome, descricao))
    print("=" * 78)
    with tempfile.TemporaryDirectory() as tmp:
        montar(tmp)
        semear(tmp)
        rc, saida = correr(os.path.join(tmp, "docs", "seguranca", "validar.py"), tmp)
        print("  codigo de saida:", rc)
        linha = next((l.strip() for l in saida.splitlines() if sinal in l), None)
        if linha:
            print("  ", linha[:150])
        confere(nome, rc == 1, "esperava codigo 1, veio %d" % rc)
        confere(nome, "Traceback" not in saida, "houve traceback")
        confere(nome, linha is not None, "a guarda nao nomeou %r" % sinal)
        confere(nome, "OK: 0 erros" not in saida, "deu «0 erros» com a fonte semeada")
        if linha and "Traceback" not in saida:
            print("  OK: erro de configuracao com mensagem, sem traceback, sem «0 erros».")

for nome, descricao, semear in IGNORADOS:
    print()
    print("=" * 78)
    print("IGNORADO %s — %s" % (nome, descricao))
    print("=" * 78)
    with tempfile.TemporaryDirectory() as tmp:
        montar(tmp)
        semear(tmp)
        rc, saida = correr(os.path.join(tmp, "docs", "seguranca", "validar.py"), tmp)
        print("  codigo de saida:", rc)
        confere(nome, "Traceback" not in saida, "houve traceback")
        confere(nome, rc in (0, 1), "codigo de saida fora de {0,1}: %d" % rc)
        confere(nome, "zz_pasta" not in saida, "a pasta entrou no relatorio")
        if "Traceback" not in saida:
            print("  OK: a travessia nao a ve, o programa corre inteiro, nada a reportar.")

for nome, descricao, semear in LIMITACOES:
    print()
    print("=" * 78)
    print("LIMITACAO %s — %s" % (nome, descricao))
    print("=" * 78)
    with tempfile.TemporaryDirectory() as tmp:
        montar(tmp)
        semear(tmp)
        rc, saida = correr(os.path.join(tmp, "docs", "seguranca", "validar.py"), tmp)
        disparou = [l for l in saida.splitlines() if "canon:" in l]
        print("  codigo de saida:", rc, "| guarda do canon disparou:", bool(disparou))
        confere(nome, not disparou, "a guarda disparou — a limitacao deixou de existir")
        confere(nome, "Traceback" not in saida, "houve traceback")
        if not disparou:
            print("  OK (limitacao confirmada): o piso ve «pouco», nao ve «errado».")

if ANTIGO:
    print()
    print("=" * 78)
    print("CASO antigo — o assert da contagem contra esta arvore: o «antes»")
    print("=" * 78)
    with tempfile.TemporaryDirectory() as tmp:
        copia = os.path.join(tmp, "validar_antigo.py")
        shutil.copy2(ANTIGO, copia)
        rc, saida = correr(copia, RAIZ)
        print("  codigo de saida:", rc)
        for l in saida.splitlines():
            if "AssertionError" in l or "assert len(KAM)" in l:
                print("    ", l.strip()[:150])
        familias = [f for f in ("MATRIZ", "STRIDE", "DPIA", "DOCS") if re.search(r"^%s" % f, saida, re.M)]
        print("  tem traceback:", "Traceback" in saida)
        print("  familias impressas:", familias or "NENHUMA")
        confere("antigo", "Traceback" in saida, "esperava traceback do validador antigo")
        confere("antigo", not familias, "o validador antigo imprimiu familias: %s" % familias)

print()
if falhas:
    print("FALHARAM %d ASSERCAO(OES):" % len(falhas))
    for f in falhas:
        print("  -", f)
    sys.exit(1)
print("TODAS AS ASSERCOES PASSARAM.")
