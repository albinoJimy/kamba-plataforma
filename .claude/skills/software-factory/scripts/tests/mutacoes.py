"""As mutacoes do KAM-185: cada uma tem de avermelhar pelo menos um ensaio.

    python .claude/skills/software-factory/scripts/tests/mutacoes.py

Cada mutacao desliga uma regra ou uma **ligacao** (o `avaliar` sem medir a fusao,
que deixa as funcoes certas e o sitio errado). Repoe o ficheiro sempre, mesmo com o
ensaio a rebentar. Sai 1 se alguma sobreviver ou nao se aplicar.

**A primeira versao tinha oito, e as oito morriam — e isso so provava os defeitos
que eu tinha escolhido.** A revisao adversarial escreveu outras nove, contra o mesmo
codigo, e as nove sobreviveram com a bateria verde: a reserva do piso, o problema do
piso na fusao, os conflitos, o filtro do assunto, o fim da tabela, o filtro do `A`.
Ficam aqui, com os ensaios que as matam, e mais as das regras que a revisao fez
nascer (buracos, cabecalho em texto, vermelhas, a ordem por prontidao, o recurso com
conflitos, o fim do bloco).
"""

import pathlib
import subprocess
import sys

PASTA = pathlib.Path(__file__).resolve().parents[1]

MUTACOES = [
    # --- as oito da primeira versao
    ("a reserva das versoes", "fila.py",
     "        reserva.versoes[caminho] = reserva.versoes.get(caminho, 0) + len(novas)\n", ""),
    ("o maximo e a ultima linha", "superficies.py",
     "    return max(numeros, key=chave) if numeros else None",
     "    return numeros[-1] if numeros else None"),
    ("a fila ordena so pelo numero", "fila.py",
     "    return sorted(avaliacoes, key=lambda av: (ORDEM[av.veredicto], av.pr.numero))",
     "    return sorted(avaliacoes, key=lambda av: av.pr.numero)"),
    ("sem o cabecalho atrasado", "superficies.py",
     "    if lido.atrasado:", "    if False:"),
    ("sem o pai em falta", "superficies.py",
     "        if pai is not None and pai not in pais:", "        if False:"),
    ("lote sem o limite de migracao", "lote.py",
     "        if c.migracao and vaga_de_migracao <= 0:", "        if False:"),
    ("a verificacao conta na previsao", "lote.py",
     "    return bloco[:corte] if corte >= 0 else bloco", "    return bloco"),
    ("a ligacao: avaliar nao mede a fusao", "fila.py",
     "    medir_contra(avaliacao, arvore, conflitos, medir)\n", ""),
    # --- as nove que sobreviviam a primeira bateria (revisao adversarial)
    ("a reserva nao acumula os medidos", "fila.py",
     "    reserva.medidos += av.delta_medidos\n", ""),
    ("a reserva nao guarda o piso", "fila.py",
     "    reserva.piso = piso\n", ""),
    ("o piso de antes ignora a reserva", "fila.py",
     "    piso_antes = max(piso_main, reserva.piso)", "    piso_antes = piso_main"),
    ("o piso da fusao nao conta", "fila.py",
     "        if problema:\n            problemas.append(problema)",
     "        if False:\n            problemas.append(problema)"),
    ("o pronto ignora os conflitos", "fila.py",
     "and not self.conflitos and not self.problemas", "and not self.problemas"),
    ("a fusao nunca tem conflitos", "fonte.py",
     "    if codigo == 1:", "    if False:"),
    ("o assunto sem filtro", "lote.py",
     "            if \" \" in linha and padrao.search(linha.split(\" \", 1)[1])]",
     "            if \" \" in linha]"),
    ("as revisoes novas sem o filtro do A", "fila.py",
     "if estado == \"A\" and sup.numero_de_revisao(c))", "if sup.numero_de_revisao(c))"),
    ("o bloco acaba so no proximo KAM", "vagas.py",
     r"(?=^## |\Z)", r"(?=^## KAM-|\Z)"),
    # --- as regras que a revisao fez nascer
    ("sem os buracos", "superficies.py",
     "                  for v in lido.buracos]", "                  for v in ()]"),
    ("o cabecalho em texto nao se le", "superficies.py",
     "    campo = em_tabela or em_texto", "    campo = em_tabela"),
    ("o pronto ignora as vermelhas", "fila.py",
     "    return github_ok and not pr.vermelhas and", "    return github_ok and"),
    ("o vermelho volta a frente", "fila.py",
     'ORDEM = {"PRONTO": 0, "PENDENTE": 1, "INTEGRAR": 2, "RASCUNHO": 3, "VERMELHO": 4}',
     'ORDEM = {"PRONTO": 0, "PENDENTE": 1, "INTEGRAR": 2, "RASCUNHO": 3, "VERMELHO": 0}'),
    ("com conflitos, as emendas pela base do ramo", "fila.py",
     "        revisoes, emendas = acrescentado(main, pr.ponta)\n",
     "        revisoes, emendas = acrescentado(base, pr.ponta)\n"),
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
    print(f"{estado} {nome}: {len(linhas)} ensaio(s) vermelho(s)", flush=True)
    for linha in linhas[:2]:
        print(f"             {linha[:110]}", flush=True)
print(f"\n{len(MUTACOES) - falhas} de {len(MUTACOES)} mortas")
sys.exit(1 if falhas else 0)
