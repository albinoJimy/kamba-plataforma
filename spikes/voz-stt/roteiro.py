"""O roteiro de enunciados e as folhas por falante (KAM-107).

    python roteiro.py folha 3        # a folha do falante 3 de 10, para imprimir

O `roteiro.tsv` tem 220 enunciados de PT-AO, escritos para esta preparação e sem
dados pessoais: preços em kwanzas, quantidades, horas e datas, moradas por bairro
de Luanda (ruas e números inventados), produtos, regateio, marcações, entregas e
atendimento. Duas marcas por linha, que são as que o manifesto usa para os grupos
do WER:

- `numeros = S` se o enunciado tem um número, preço, quantidade ou hora;
- `linguas = S` se tem pelo menos uma palavra da lista abaixo.

**A lista é uma proposta do executor e a origem das palavras é NÃO VERIFICADO.**
São palavras de uso corrente no português de Angola que o executor dá como vindas
do Kimbundu ou do Umbundu, mais três saudações e agradecimentos; nenhuma fonte do
conjunto as confirma. O protocolo de gravação (§3) manda um anotador falante
confirmar ou corrigir a lista **antes** de gravar, e uma linha cuja única palavra
caia passa a `linguas = N`. Os topónimos (Kilamba, Cazenga, Kikolo) não contam:
o critério fala de palavras e não de nomes de lugar.

**As folhas** repartem o roteiro por 10 falantes, 22 enunciados cada, por
distribuição estratificada: cada folha fica com a mesma mistura de números e de
línguas que o roteiro todo, para que um falante não leve só preços e outro só
moradas. Em cada folha, 6 enunciados vão marcados para gravar **em ruído**
(27%, acima dos 20% do critério, com folga para clips que se percam).
"""

from __future__ import annotations

import sys
import unicodedata

from manifesto import Enunciado, ler_roteiro

FALANTES = 10

#: NÃO VERIFICADO — ver o docstring. Formas sem acentos e em minúsculas.
PALAVRAS_DE_LINGUAS_NACIONAIS = frozenset(
    {
        "cacimbo",
        "caxinde",
        "dikanza",
        "funje",
        "jindungo",
        "kamba",
        "kandengue",
        "kandengues",
        "kilapi",
        "kissangua",
        "kitaba",
        "kitanda",
        "kizaka",
        "kota",
        "kumbu",
        "maka",
        "makezu",
        "mambo",
        "muadie",
        "muamba",
        "mufete",
        "ndapandula",
        "ngana",
        "ngasakidila",
        "quissange",
        "wakolapo",
        "zungueira",
    }
)


def palavras(texto: str) -> list[str]:
    sem = "".join(c for c in unicodedata.normalize("NFD", texto.lower()) if unicodedata.category(c) != "Mn")
    return "".join(c if c.isalnum() else " " for c in sem).split()


def marcadas(texto: str) -> list[str]:
    return [p for p in palavras(texto) if p in PALAVRAS_DE_LINGUAS_NACIONAIS]


def folhas(roteiro: dict[str, Enunciado], n: int = FALANTES) -> list[list[Enunciado]]:
    """Estratifica por (línguas, números) e reparte em ciclo, pela ordem do id."""
    estratos: dict[tuple[bool, bool], list[Enunciado]] = {}
    for e in sorted(roteiro.values(), key=lambda e: e.id):
        estratos.setdefault((e.linguas, e.numeros), []).append(e)
    saida: list[list[Enunciado]] = [[] for _ in range(n)]
    i = 0
    for chave in sorted(estratos, reverse=True):
        for e in estratos[chave]:
            saida[i % n].append(e)
            i += 1
    for f in saida:
        f.sort(key=lambda e: e.id)
    return saida


def em_ruido(posicao: int) -> bool:
    """6 em 22: as posições 2, 5, 9, 12, 16 e 19 de cada folha (a contar de 0)."""
    return posicao % 7 in (2, 5)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2 or args[0] != "folha" or not args[1].isdigit() or not 1 <= int(args[1]) <= FALANTES:
        print(f"uso: python roteiro.py folha 1..{FALANTES}", file=sys.stderr)
        return 2
    folha = folhas(ler_roteiro())[int(args[1]) - 1]
    print(f"Folha {args[1]} de {FALANTES} — {len(folha)} enunciados. [RUÍDO] grava-se no ambiente ruidoso.")
    for i, e in enumerate(folha):
        marca = " [RUÍDO]" if em_ruido(i) else ""
        print(f"{e.id}{marca}  {e.texto}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
