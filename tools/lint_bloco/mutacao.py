"""Varredura de mutacao sobre o proprio `lint_bloco`: a regra morde ou nao?

    python tools/lint_bloco/mutacao.py            # a varredura
    python tools/lint_bloco/mutacao.py --lista    # so os pontos, sem correr

**Porque e que isto esta no repositorio e nao num *scratchpad*.** A primeira
versao deste ticket afirmava que os ensaios mordiam, com base numa varredura que
correu numa pasta temporaria e desapareceu. A revisao adversarial montou a sua e
**metade das mutacoes sobrevivia** — entre elas a ordem das listas de
vocabulario, o salto de cercas e os dois pisos de cobertura. Uma afirmacao sobre
a forca dos ensaios que nao vem com o instrumento e `INDICIO`, nao
`CONFIRMADO`, e esta casa ja escreveu a regra: «as contagens tem comando, e o
comando esta no repositorio».

## COMO FUNCIONA

Para cada ponto: copia `tools/lint_bloco`, `tools/lint_backlog`,
`tools/kamba_yaml.py`, `specs/` e `ci/` para uma pasta propria, aplica **uma**
mutacao, e corre os ensaios **e** o canario contra essa copia. Uma mutacao que
deixe os dois verdes **sobreviveu**: e um ponto que nenhuma prova prende.

**O controlo corre primeiro e tem de ser verde.** Sem ele, N vermelhos a seguir
podiam ser o mesmo defeito N vezes — e a varredura dizia «tudo apanhado» sobre
uma copia que nao corre.

**Nao se copia o `tools/` inteiro de proposito:** o `tools/meta-sim/node_modules`
tem ligacoes simbolicas para `packages/`, e um `copytree` delas falha num
*worktree*. Copiam-se os tres caminhos de que o *lint* precisa.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]

#: O que se copia: **so o que se muta**, mais as superficies que o *lint* le.
#:
#: **A cópia sombreia, nao substitui.** O `PYTHONPATH` leva a `tools` da copia
#: **antes** da `tools` real, pelo que o `lint_bloco` resolve-se da copia (onde a
#: mutacao esta) e tudo o que ele importa — `lint_backlog`, e o `lint_refs` e o
#: `lint_handoff` que vem atras dele — resolve-se da arvore real, sem mutacao.
#:
#: **A primeira versao copiava a cadeia de importacoes a mao e o controlo ficava
#: vermelho** com `ModuleNotFoundError`, duas vezes, porque a cadeia e mais longa
#: do que parece (`lint_bloco` -> `lint_backlog` -> `lint_refs` -> `lint_handoff`).
#: E e o argumento para o controlo existir: sem ele, as 20 mutacoes davam 20
#: «mortes» que eram todas o mesmo erro de importacao, e a varredura reportava
#: «tudo apanhado».
A_COPIAR = (
    "tools/lint_bloco",
    "specs",
    "ci",
)

#: `(nome, ficheiro, velho, novo)`. O `velho` tem de existir **tal e qual**, e
#: uma mutacao que nao aplique e reportada em vez de contada como morta — senao
#: uma renomeacao fazia a varredura dizer «tudo apanhado» sem mutar nada.
MUTACOES: tuple[tuple[str, str, str, str], ...] = (
    # ---------------------------------------------------- o nucleo da regra
    ("comparacao em contagem e nao par a par", "lint.py",
     "        if classe != caixa.marcada and bloco.id not in dispensas:",
     "        if classes.count(True) != sum(1 for c in par.caixas if c.marcada) "
     "and bloco.id not in dispensas:"),
    ("a regra desligada", "lint.py",
     "        if classe != caixa.marcada and bloco.id not in dispensas:",
     "        if False:"),
    ("o `!=` invertido", "lint.py",
     "        if classe != caixa.marcada and bloco.id not in dispensas:",
     "        if classe == caixa.marcada and bloco.id not in dispensas:"),
    ("as caixas emparelhadas ao contrario", "lint.py",
     "    for indice, (caixa, estado) in enumerate(zip(par.caixas, par.estados), start=1):",
     "    for indice, (caixa, estado) in enumerate(zip(par.caixas[::-1], par.estados), start=1):"),
    ("as dispensas ignoradas", "lint.py",
     "        if classe != caixa.marcada and bloco.id not in dispensas:",
     "        if classe != caixa.marcada:"),
    # ------------------------------------------------------ o emparelhamento
    ("a correspondencia um-a-um deixa de ser exigida", "lint.py",
     "        if len(tabela.estados) != len(caixas):",
     "        if False:"),
    ("a convencao da tabela combinada removida", "lint.py",
     "    elif linhas == len(bloco.criterios) + len(bloco.dod) and bloco.criterios:",
     "    elif False:"),
    ("a tabela da DoD ignorada", "lint.py",
     "    if tab_dod is not None:",
     "    if False:"),
    ("a tabela escolhida e a ultima e nao a primeira", "modelo.py",
     "        for tabela in self.tabelas:\n            if tabela.especie == especie:\n                return tabela\n        return None",
     "        encontradas = [t for t in self.tabelas if t.especie == especie]\n"
     "        return encontradas[-1] if encontradas else None"),
    # ------------------------------------------------------- o vocabulario
    # **M10 e M11 sobrevivem, e e esperado.** Com o vocabulario de hoje a ordem
    # das tres listas nao muda nenhum resultado: o termo de uma celula composta
    # e o primeiro (`vazia, satisfeito` -> `vazia`), e nenhum termo de uma lista
    # e tambem termo de outra. Ficam na varredura para que o dia em que **passem
    # a morder** se veja — e o `SOBREVIVENTES_ESPERADAS` abaixo diz que nao sao
    # defeito.
    ("a ordem das listas: FEITO antes de POR_FAZER", "modelo.py",
     "    for lista, veredicto in ((ESTADOS_SEM_CLASSE, None),\n"
     "                             (ESTADOS_POR_FAZER, False),\n"
     "                             (ESTADOS_FEITO, True)):\n"
     "        if texto in lista:\n            return veredicto",
     "    for lista, veredicto in ((ESTADOS_SEM_CLASSE, None),\n"
     "                             (ESTADOS_FEITO, True),\n"
     "                             (ESTADOS_POR_FAZER, False)):\n"
     "        if texto in lista:\n            return veredicto"),
    ("as SEM_CLASSE provadas em ultimo", "modelo.py",
     "    for lista, veredicto in ((ESTADOS_SEM_CLASSE, None),\n"
     "                             (ESTADOS_POR_FAZER, False),\n"
     "                             (ESTADOS_FEITO, True)):\n"
     "        if texto in lista:\n            return veredicto",
     "    for lista, veredicto in ((ESTADOS_POR_FAZER, False),\n"
     "                             (ESTADOS_FEITO, True),\n"
     "                             (ESTADOS_SEM_CLASSE, None)):\n"
     "        if texto in lista:\n            return veredicto"),
    # **Aponta-se ao PRIMEIRO ciclo e nao ao segundo**, e a diferenca foi medida:
    # com a mutacao no segundo, o `return None` antecipado (quando nao ha
    # justificacao a cortar) torna-o inalcancavel para `verde-azulado`, e a
    # mutacao sobrevivia sem mudar comportamento nenhum. Uma mutacao que nao
    # muta e um falso sobrevivente, e e pior do que nao a ter.
    ("o casamento volta a ser por prefixo nu", "modelo.py",
     "        if texto in lista:\n            return veredicto",
     "        if any(texto.startswith(x) for x in lista):\n            return veredicto"),
    ("a justificacao deixa de se cortar", "modelo.py",
     "    termo = _termo_da_celula(texto)",
     "    termo = texto"),
    # ---------------------------------------------------------- o *parser*
    ("o salto de cercas desligado", "modelo.py",
     "    visiveis = list(fora_de_cerca(texto))",
     "    visiveis = list(enumerate(texto.split('\\n'), 1))"),
    ("a coluna de assunto volta a casar por sub-cadeia", "modelo.py",
     "    if any(c in COLUNAS_DE_ASSUNTO for c in limpas):",
     "    if any(any(p in c for p in COLUNAS_DE_ASSUNTO) for c in limpas):"),
    ("o indice da coluna de Estado fixado a zero", "modelo.py",
     "            [limpo(c) for c in cabecalho].index(COLUNA_DE_ESTADO)",
     "            0"),
    ("o `|` escapado volta a separar celulas", "modelo.py",
     "    partes = _SEPARADOR_DE_CELULA.split(linha)[1:-1]",
     "    partes = linha.split('|')[1:-1]"),
    ("um titulo de nivel 4 volta a abrir seccao", "modelo.py",
     '            if titulo.group(1) == "###":',
     "            if True:"),
    # ------------------------------------------------------- os dois pisos
    ("o piso de blocos a zero", "lint.py",
     "MINIMO_DE_BLOCOS = 150", "MINIMO_DE_BLOCOS = 0"),
    ("o piso de emparelhados a zero", "lint.py",
     "MINIMO_DE_BLOCOS_MEDIDOS = 40", "MINIMO_DE_BLOCOS_MEDIDOS = 0"),
)


#: As mutacoes que **nao** se espera que morram, com a razao.
#:
#: Uma varredura que exija zero sobreviventes empurra para inventar um caso de
#: ensaio que faca morder uma mutacao que nao muda comportamento nenhum — e um
#: ensaio desses e pior do que a ausencia dele. Declaram-se, e a saida distingue
#: «sobreviveu» de «sobreviveu como esperado».
SOBREVIVENTES_ESPERADAS = {
    "a ordem das listas: FEITO antes de POR_FAZER":
        "com o vocabulario de hoje a ordem nao muda resultado nenhum: o termo "
        "de uma celula composta e o primeiro, e nenhum termo de uma lista e "
        "tambem termo de outra",
    "as SEM_CLASSE provadas em ultimo": "a mesma razao da de cima",
}


def _copiar(destino: Path) -> None:
    for caminho in A_COPIAR:
        origem = RAIZ / caminho
        alvo = destino / caminho
        alvo.parent.mkdir(parents=True, exist_ok=True)
        if origem.is_dir():
            shutil.copytree(origem, alvo,
                            ignore=shutil.ignore_patterns("__pycache__",
                                                          "node_modules"))
        else:
            shutil.copy2(origem, alvo)


def _correr(copia: Path) -> int:
    """0 se os ensaios **e** o canario passarem naquela copia."""
    ambiente = dict(os.environ)
    # A ordem **importa**: a copia primeiro, para sombrear o `lint_bloco`; a
    # arvore real atras, para tudo o que ele importa. E `os.pathsep`, que nesta
    # maquina e `;` — um `:` nao separa nada e o caminho inteiro ficava invalido.
    ambiente["PYTHONPATH"] = os.pathsep.join([
        str(copia / "tools"),
        str(RAIZ / "tools"),
        str(RAIZ / "libs" / "py-core" / "src"),
    ])
    ambiente["PYTHONDONTWRITEBYTECODE"] = "1"
    for argumentos in (
            [sys.executable, "-m", "unittest", "discover",
             "-s", "lint_bloco/tests", "-t", "."],
            [sys.executable, "-m", "lint_bloco", "--root", str(copia), "canario"],
    ):
        resultado = subprocess.run(argumentos, cwd=copia / "tools",
                                   capture_output=True, text=True, env=ambiente)
        if resultado.returncode != 0:
            return resultado.returncode
    return 0


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="mutacao")
    parser.add_argument("--lista", action="store_true",
                        help="imprime os pontos e nao corre nada")
    args = parser.parse_args(argv)

    if args.lista:
        for nome, ficheiro, _, _ in MUTACOES:
            print(f"  {ficheiro:<10} {nome}")
        print(f"\n{len(MUTACOES)} pontos")
        return 0

    trabalho = Path(os.environ.get("TEMP", "/tmp")) / "lint-bloco-mutacao"
    shutil.rmtree(trabalho, ignore_errors=True)
    trabalho.mkdir(parents=True)

    base = trabalho / "controlo"
    _copiar(base)
    codigo = _correr(base)
    print(f"{'CONTROLO (sem mutacao)':<52} "
          f"{'verde' if codigo == 0 else 'VERMELHO — a varredura nao vale'}")
    if codigo != 0:
        print("  o controlo tem de ser verde; parei aqui", file=sys.stderr)
        return 2

    mortas: list[str] = []
    sobreviventes: list[str] = []
    invalidas: list[str] = []
    for indice, (nome, ficheiro, velho, novo) in enumerate(MUTACOES, start=1):
        copia = trabalho / f"m{indice:02d}"
        _copiar(copia)
        alvo = copia / "tools" / "lint_bloco" / ficheiro
        texto = alvo.read_text(encoding="utf-8")
        if velho not in texto:
            invalidas.append(nome)
            print(f"M{indice:02d} {nome:<48} NAO APLICOU — o texto mudou")
            continue
        alvo.write_text(texto.replace(velho, novo, 1), encoding="utf-8")
        if _correr(copia) == 0:
            if nome in SOBREVIVENTES_ESPERADAS:
                print(f"M{indice:02d} {nome:<48} sobreviveu (esperado)")
            else:
                sobreviventes.append(nome)
                print(f"M{indice:02d} {nome:<48} SOBREVIVEU")
        else:
            mortas.append(nome)
            print(f"M{indice:02d} {nome:<48} morta")

    print()
    print(f"{len(mortas)} mortas, {len(sobreviventes)} sobreviventes "
          f"inesperadas, {len(SOBREVIVENTES_ESPERADAS)} esperadas, "
          f"{len(invalidas)} invalidas, de {len(MUTACOES)} pontos")
    for nome in sobreviventes:
        print(f"  SOBREVIVEU: {nome}")
    return 1 if (sobreviventes or invalidas) else 0


if __name__ == "__main__":
    sys.exit(main())
