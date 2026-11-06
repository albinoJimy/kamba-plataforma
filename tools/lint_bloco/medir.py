"""Produz **todos** os numeros que o KAM-183 cita, com o predicado de cada um.

    python tools/lint_bloco/medir.py

**Porque e que isto esta no repositorio.** A primeira versao deste ticket citava
dez numeros — «121 dos 125 blocos», «52 primeiras-palavras», «646 celulas de
satisfeito», «25% de alarme» — medidos por *scripts* que correram numa pasta
temporaria e desapareceram. A revisao adversarial montou vinte receitas e **nao
reproduziu nenhum deles**: a conclusao mantinha-se, os numeros nao. Um numero
reconstruido a mao e `INDICIO`, nao `CONFIRMADO`, e esta casa ja tem a regra
escrita no `tools/obs_lint/contar_metricas.py`: «uma contagem feita antes de se
definir o que conta produz numeros errados com a mesma firmeza com que produziria
os certos».

Por isso **cada seccao declara o seu predicado antes do numero**, e a prosa do
`docs/lint-bloco.md` cita esta saida em vez de a parafrasear.

## OS PREDICADOS, escritos antes de contar

1. **Bloco**: um titulo `## KAM-NNN — ` fora de cerca, nos epics e em
   `specs/tickets/`. Fecha no titulo de bloco seguinte **ou em qualquer `##`**.
2. **Seccao de verificacao**: o bloco tem um titulo de nivel 3 ou 4 que comece
   por «Verifica».
3. **Tabela de estados**: uma tabela do bloco cujo cabecalho tenha uma celula
   `Estado` (depois de tirar enfase e minusculizar).
4. **Primeira-palavra de uma celula de estado**: o **termo** do
   `modelo._termo_da_celula` — a cadeia ate ao primeiro separador seguido de
   espaco. E o mesmo predicado que a classificacao usa, de proposito: um numero
   medido com outro predicado nao descreve o que o *lint* faz.
5. **Regra ingenua** (a que o pedido original descrevia): o numero de `- [x]` do
   bloco iguala o numero de celulas de estado cujo termo e `marcada`.
6. **Par numero/prosa**: um par (caixa, linha de tabela) de um bloco
   emparelhado. «Tem numeros» quer dizer que o texto da caixa tem pelo menos um
   inteiro, com fronteira (`(?<![\\w§.,])\\d+(?![\\w.,%])`). «Concorda» quer
   dizer que **todos** os inteiros da caixa aparecem na **celula de evidencia**
   da sua linha — a ultima celula da linha.
"""

from __future__ import annotations

import collections
import re
import sys
from pathlib import Path

from lint_bloco import lint, modelo

RAIZ = Path(__file__).resolve().parents[2]

#: Um inteiro com fronteira, para o predicado 6. Exclui `§4`, `1.2` e `80%`.
INTEIRO = re.compile(r"(?<![\w§.,])(\d+)(?![\w.,%])")

TITULO_DE_VERIFICACAO = re.compile(r"^#{3,4}\s*.*Verifica", re.I)


def _tem_seccao_de_verificacao(bloco: modelo.Bloco, texto: str) -> bool:
    """Predicado 2, sobre as linhas do bloco."""
    linhas = texto.split("\n")
    fim = len(linhas)
    for numero, linha in modelo.fora_de_cerca(texto):
        if numero > bloco.numero and (modelo.TITULO_DE_BLOCO.match(linha)
                                      or linha.startswith("## ")):
            fim = numero
            break
    return any(TITULO_DE_VERIFICACAO.match(l)
               for l in linhas[bloco.numero:fim - 1])


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    blocos = modelo.ler_blocos(RAIZ)
    por_ficheiro: dict[str, str] = {}
    for bloco in blocos:
        por_ficheiro.setdefault(
            bloco.ficheiro, (RAIZ / bloco.ficheiro).read_text(encoding="utf-8"))

    com_verificacao = [b for b in blocos
                       if _tem_seccao_de_verificacao(b, por_ficheiro[b.ficheiro])]
    com_tabela = [b for b in blocos if b.tabelas]
    uniao = {b.id for b in com_verificacao} | {b.id for b in com_tabela}

    print("=" * 72)
    print("A POPULACAO  (predicados 1, 2 e 3)")
    print(f"  blocos                                        {len(blocos)}")
    print(f"  com seccao de verificacao                     {len(com_verificacao)}")
    print(f"  com tabela de coluna `Estado`                 {len(com_tabela)}")
    print(f"  uniao dos dois                                {len(uniao)}")

    # ------------------------------------------------- o vocabulario (pred. 4)
    termos: collections.Counter[str] = collections.Counter()
    celulas_totais = 0
    sem_coluna_de_estado = 0
    for bloco in blocos:
        for tabela in bloco.tabelas:
            for estado in tabela.estados:
                celulas_totais += 1
                termos[modelo._termo_da_celula(modelo.limpo(estado))] += 1
    # As tabelas que tem coluna de assunto e **nao** tem `Estado` nao entram em
    # `bloco.tabelas` (o `_tabelas` descarta-as), pelo que se contam a parte.
    for ficheiro, texto in por_ficheiro.items():
        linhas = [l for _, l in modelo.fora_de_cerca(texto)]
        for indice, linha in enumerate(linhas[:-1]):
            if not (linha.startswith("|")
                    and modelo.SEPARADOR.match(linhas[indice + 1])):
                continue
            cabecalho = [modelo.limpo(c) for c in modelo.celulas(linha)]
            if modelo.COLUNA_DE_ESTADO in cabecalho:
                continue
            if any(c in modelo.COLUNAS_DE_ASSUNTO for c in cabecalho):
                sem_coluna_de_estado += 1

    print()
    print("O VOCABULARIO DA COLUNA `Estado`  (predicado 4)")
    print(f"  celulas de estado                             {celulas_totais}")
    print(f"  termos distintos                              {len(termos)}")
    print(f"  tabelas com coluna de assunto e sem `Estado`   {sem_coluna_de_estado}")
    print("  os dez termos mais frequentes:")
    for termo, quantas in termos.most_common(10):
        print(f"      {quantas:>5}  {termo!r}")

    # ------------------------------------------------- a regra ingenua (pred. 5)
    ingenua_vermelhos = 0
    for bloco in blocos:
        if bloco.id not in uniao:
            continue
        marcadas = sum(1 for c in bloco.criterios + bloco.dod if c.marcada)
        celulas_marcada = sum(
            1 for t in bloco.tabelas for e in t.estados
            if modelo._termo_da_celula(modelo.limpo(e)) == "marcada")
        if marcadas != celulas_marcada:
            ingenua_vermelhos += 1
    print()
    print("A REGRA INGENUA, a que o pedido original descrevia  (predicado 5)")
    print(f"  blocos da uniao                               {len(uniao)}")
    print(f"  que ela poria a vermelho                      {ingenua_vermelhos}")
    print(f"  ou seja                                       "
          f"{100 * ingenua_vermelhos // max(1, len(uniao))}%")

    # ------------------------------------------- o que o *lint* mede hoje
    dispensas = frozenset()
    achados, nao_medidos, numeros = lint.verificar(RAIZ, dispensas)
    categorias = collections.Counter(n.categoria for n in nao_medidos)
    blocos_com_achado = set()
    indice_por_ficheiro: dict[str, list[modelo.Bloco]] = {}
    for bloco in blocos:
        indice_por_ficheiro.setdefault(bloco.ficheiro, []).append(bloco)
    for achado in achados:
        ficheiro, linha = achado.onde.rsplit(":", 1)
        candidatos = [b for b in indice_por_ficheiro[ficheiro]
                      if b.numero <= int(linha)]
        blocos_com_achado.add(max(candidatos, key=lambda b: b.numero).id)

    print()
    print("O QUE O *LINT* MEDE HOJE  (sem dispensas)")
    print(f"  blocos                                        {numeros['blocos']}")
    print(f"  emparelhados                                  {numeros['medidos']}")
    print(f"  achados                                       {numeros['achados']}")
    print(f"  em quantos blocos                             {len(blocos_com_achado)}")
    for categoria, quantas in categorias.most_common():
        print(f"  nao medido ({quantas:>3})  {categoria}")

    # --------------------------------------- a regra dos numeros (predicado 6)
    pares = sem_numeros = concordam = divergem = 0
    for bloco in blocos:
        emparelhados, _ = lint.emparelhar(bloco)
        if not emparelhados:
            continue
        linhas = [l for _, l in modelo.fora_de_cerca(por_ficheiro[bloco.ficheiro])]
        for par in emparelhados:
            numero_da_tabela = int(par.onde_tabela.rsplit(":", 1)[1])
            corpo: list[str] = []
            indice = numero_da_tabela + 1
            while indice < len(linhas) and linhas[indice].startswith("|"):
                if not modelo.SEPARADOR.match(linhas[indice]):
                    corpo.append(linhas[indice])
                indice += 1
            for caixa, linha in zip(par.caixas, corpo):
                pares += 1
                na_caixa = set(INTEIRO.findall(caixa.texto))
                if not na_caixa:
                    sem_numeros += 1
                    continue
                celulas = modelo.celulas(linha)
                evidencia = celulas[-1] if celulas else ""
                if na_caixa <= set(INTEIRO.findall(evidencia)):
                    concordam += 1
                else:
                    divergem += 1

    com_numeros = concordam + divergem
    print()
    print("A REGRA DOS NUMEROS, que NAO se entrega  (predicado 6)")
    print(f"  pares comparaveis                             {pares}")
    print(f"  sem numeros na caixa                          {sem_numeros}")
    print(f"  com numeros, a concordar                      {concordam}")
    print(f"  com numeros, a divergir                       {divergem}")
    print(f"  taxa de alarme sobre os pares com numeros     "
          f"{100 * divergem / max(1, com_numeros):.0f}%")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main())
