"""Oito mutacoes do KAM-185: cada uma tem de avermelhar pelo menos um ensaio.

    python .claude/skills/software-factory/scripts/tests/mutacoes.py

Cada mutacao desliga uma regra ou uma **ligacao** (a ultima: o `avaliar` sem medir
a fusao, que deixa as funcoes certas e o sitio errado). Repoe o ficheiro sempre,
mesmo com o ensaio a rebentar. Sai 1 se alguma sobreviver ou nao se aplicar.
"""

import pathlib
import subprocess
import sys

PASTA = pathlib.Path(__file__).resolve().parents[1]

MUTACOES = [
    ("a reserva das versoes", "fila.py",
     "        reserva.versoes[caminho] = reserva.versoes.get(caminho, 0) + len(novas)\n", ""),
    ("o maximo e a ultima linha", "superficies.py",
     "    return max(numeros, key=chave) if numeros else None",
     "    return numeros[-1] if numeros else None"),
    ("a fila ordena so pelo numero", "fila.py",
     "    return sorted(avaliacoes, key=lambda av: (not av.pronto, av.pr.numero))",
     "    return sorted(avaliacoes, key=lambda av: av.pr.numero)"),
    ("sem o cabecalho", "superficies.py",
     "    if topo and topo_do_cabecalho and topo_do_cabecalho != topo:",
     "    if False:"),
    ("sem o pai em falta", "superficies.py",
     "        if pai is not None and pai not in pais:",
     "        if False:"),
    ("lote sem o limite de migracao", "lote.py",
     "        if c.migracao and vaga_de_migracao <= 0:",
     "        if False:"),
    ("a verificacao conta na previsao", "lote.py",
     "    return bloco[:corte] if corte >= 0 else bloco",
     "    return bloco"),
    ("a ligacao: avaliar nao mede a fusao", "fila.py",
     "    medir_contra(avaliacao, main, medir)\n", ""),
]

falhas = 0
for nome, ficheiro, velho, novo in MUTACOES:
    alvo = PASTA / ficheiro
    original = alvo.read_text(encoding="utf-8")
    if original.count(velho) != 1:
        print(f"INAPLICAVEL  {nome}: achei {original.count(velho)}")
        falhas += 1
        continue
    alvo.write_text(original.replace(velho, novo), encoding="utf-8", newline="\n")
    try:
        feito = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests",
                                "-t", "tests"], cwd=PASTA, capture_output=True, text=True)
    finally:
        alvo.write_text(original, encoding="utf-8", newline="\n")
    linhas = [l for l in feito.stderr.splitlines() if l.startswith(("FAIL:", "ERROR:"))]
    estado = "MORTA     " if feito.returncode != 0 else "SOBREVIVE "
    if feito.returncode == 0:
        falhas += 1
    print(f"{estado} {nome}: {len(linhas)} ensaio(s) vermelho(s)")
    for linha in linhas[:2]:
        print(f"             {linha[:110]}")
print(f"\n{len(MUTACOES) - falhas} de {len(MUTACOES)} mortas")
sys.exit(1 if falhas else 0)
