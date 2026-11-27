"""O manifesto do corpus do spike de voz, e a verificação das quotas (KAM-107).

O manifesto é um CSV que o operador preenche **fora do repositório**: descreve
áudio de pessoas, e áudio e transcrições de pessoas não entram nesta árvore. Aqui
fica o esquema e o verificador. Uma linha por clip:

    clip_id      C0001                    identificador do clip, sem significado
    tipo         enunciado | latencia     um enunciado do roteiro, ou um clip
                                          montado de 5, 15 ou 30 s para a latência
    falante_id   F01                      **pseudónimo**; a chave para o nome
                                          vive só no arquivo dos consentimentos
    enunciados   E001  ou  E001+E002      do roteiro; o de latência pode juntar
    ficheiro     F01/C0001.ogg            relativo à pasta do áudio, sem «..»
    duracao_s    7.4                      medida por `transcodificar.sh duracao`
    ambiente     silencioso | ruidoso
    ref_a        texto                    transcrição do anotador A
    ref_b        texto                    transcrição do anotador B
    ref          texto                    a reconciliada; é esta que o WER usa

As quotas são as do critério 1 do bloco, **à letra e como *proposta***: ≥ 10
falantes, ≥ 200 enunciados de 5 a 30 s, ≥ 40% com números, ≥ 20% com palavras de
Kimbundu ou Umbundu ou mistura de línguas, ≥ 20% em ambiente ruidoso, e
divergência entre anotadores ≤ 3%. As duas marcas de grupo — números e línguas —
leem-se do `roteiro.tsv` pelo enunciado, e não do manifesto, para que não haja
duas fontes a dizer o mesmo.

**A divergência entre anotadores é o WER micro de A contra B** (leitura proposta,
`H7_Voz_STT.md` §2), pela mesma normalização: «divergência ≤ 3% reconciliada»
lê-se como a divergência medida **antes** de reconciliar ficar em ≤ 3% e todos os
clips terem a reconciliada preenchida.
"""

from __future__ import annotations

import csv
import re
import sys
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path, PurePosixPath
from typing import Iterable

from wer import agregar, alinhar

AQUI = Path(__file__).resolve().parent
ROTEIRO = AQUI / "roteiro.tsv"

CABECALHO = ("clip_id", "tipo", "falante_id", "enunciados", "ficheiro", "duracao_s", "ambiente", "ref_a", "ref_b", "ref")
TIPOS = ("enunciado", "latencia")
AMBIENTES = ("silencioso", "ruidoso")

FALANTES_MIN = 10
ENUNCIADOS_MIN = 200
DURACAO_MIN_S = Decimal(5)
DURACAO_MAX_S = Decimal(30)
NUMEROS_MIN = Decimal("0.40")
LINGUAS_MIN = Decimal("0.20")
RUIDO_MIN = Decimal("0.20")
DIVERGENCIA_MAX = Decimal("0.03")
#: Os três tamanhos da latência, e a folga do corte (*proposta*: o
#: `transcodificar.sh juntar` corta ao alvo, e o Opus arredonda a tramas de 20 ms).
TAMANHOS_S = (5, 15, 30)
FOLGA_S = Decimal("0.5")

_CLIP = re.compile(r"C\d{4}")
_FALANTE = re.compile(r"F\d{2}")
_ENUNCIADOS = re.compile(r"E\d{3}(?:\+E\d{3})*")


@dataclass(frozen=True)
class Enunciado:
    id: str
    tema: str
    numeros: bool
    linguas: bool
    texto: str


@dataclass(frozen=True)
class Clip:
    clip_id: str
    tipo: str
    falante_id: str
    enunciados: tuple[str, ...]
    ficheiro: str
    duracao_s: Decimal
    ambiente: str
    ref_a: str
    ref_b: str
    ref: str


class ManifestoInvalido(ValueError):
    pass


def ler_roteiro(caminho: Path = ROTEIRO) -> dict[str, Enunciado]:
    with open(caminho, encoding="utf-8", newline="") as f:
        linhas = list(csv.DictReader(f, delimiter="\t"))
    roteiro: dict[str, Enunciado] = {}
    for linha in linhas:
        e = Enunciado(
            id=linha["id"],
            tema=linha["tema"],
            numeros=linha["numeros"] == "S",
            linguas=linha["linguas"] == "S",
            texto=linha["texto"],
        )
        if e.id in roteiro:
            raise ManifestoInvalido(f"roteiro com id repetido: {e.id}")
        roteiro[e.id] = e
    return roteiro


def ler(caminho: Path | str) -> list[Clip]:
    with open(caminho, encoding="utf-8", newline="") as f:
        leitor = csv.DictReader(f)
        if tuple(leitor.fieldnames or ()) != CABECALHO:
            raise ManifestoInvalido(f"cabeçalho tem de ser exactamente {','.join(CABECALHO)}")
        clips = []
        for n, linha in enumerate(leitor, start=2):
            try:
                duracao = Decimal(linha["duracao_s"])
            except InvalidOperation:
                raise ManifestoInvalido(f"linha {n}: duracao_s ilegível") from None
            clips.append(
                Clip(
                    clip_id=linha["clip_id"],
                    tipo=linha["tipo"],
                    falante_id=linha["falante_id"],
                    enunciados=tuple(linha["enunciados"].split("+")),
                    ficheiro=linha["ficheiro"],
                    duracao_s=duracao,
                    ambiente=linha["ambiente"],
                    ref_a=linha["ref_a"],
                    ref_b=linha["ref_b"],
                    ref=linha["ref"],
                )
            )
    return clips


def tamanho(duracao_s: Decimal) -> int | None:
    """O tamanho de latência a que um clip pertence, ou `None`."""
    for alvo in TAMANHOS_S:
        if abs(duracao_s - alvo) <= FOLGA_S:
            return alvo
    return None


def grupos(clip: Clip, roteiro: dict[str, Enunciado]) -> tuple[str, ...]:
    """Os grupos do WER a que o clip pertence. `global` é sempre o primeiro."""
    saida = ["global"]
    enunciados = [roteiro[e] for e in clip.enunciados if e in roteiro]
    if any(e.numeros for e in enunciados):
        saida.append("numeros")
    if any(e.linguas for e in enunciados):
        saida.append("linguas")
    saida.append(clip.ambiente)
    return tuple(saida)


def _fraccao(parte: int, todo: int) -> Decimal:
    return Decimal(parte) / Decimal(todo) if todo else Decimal(0)


def verificar(clips: Iterable[Clip], roteiro: dict[str, Enunciado]) -> list[str]:
    """Tudo o que falta ou está errado, de uma vez. Lista vazia é conforme."""
    achados: list[str] = []
    lista = list(clips)
    vistos: set[str] = set()
    for c in lista:
        onde = c.clip_id or "(sem clip_id)"
        if not _CLIP.fullmatch(c.clip_id):
            achados.append(f"{onde}: clip_id fora da forma C0000")
        if c.clip_id in vistos:
            achados.append(f"{onde}: clip_id repetido")
        vistos.add(c.clip_id)
        if c.tipo not in TIPOS:
            achados.append(f"{onde}: tipo desconhecido {c.tipo!r}")
        if not _FALANTE.fullmatch(c.falante_id):
            achados.append(f"{onde}: falante_id tem de ser pseudónimo F00, nunca um nome")
        if not _ENUNCIADOS.fullmatch("+".join(c.enunciados)):
            achados.append(f"{onde}: enunciados fora da forma E000[+E000]")
        desconhecidos = [e for e in c.enunciados if e not in roteiro]
        if desconhecidos:
            achados.append(f"{onde}: enunciados fora do roteiro: {', '.join(desconhecidos)}")
        p = PurePosixPath(c.ficheiro)
        if p.is_absolute() or ".." in p.parts or "\\" in c.ficheiro or ":" in c.ficheiro:
            achados.append(f"{onde}: ficheiro tem de ser relativo à pasta do áudio, sem «..»")
        elif not p.parts or p.parts[0] != c.falante_id:
            achados.append(f"{onde}: ficheiro tem de estar na pasta do seu falante ({c.falante_id}/...)")
        if p.suffix != ".ogg":
            achados.append(f"{onde}: ficheiro tem de ser .ogg (Opus/OGG, como no WhatsApp)")
        if c.ambiente not in AMBIENTES:
            achados.append(f"{onde}: ambiente desconhecido {c.ambiente!r}")
        if c.tipo == "enunciado":
            if len(c.enunciados) != 1:
                achados.append(f"{onde}: um enunciado tem um só id do roteiro")
            if not DURACAO_MIN_S <= c.duracao_s <= DURACAO_MAX_S:
                achados.append(f"{onde}: duração {c.duracao_s} s fora de 5 a 30 s")
            for campo in ("ref_a", "ref_b", "ref"):
                if not getattr(c, campo).strip():
                    achados.append(f"{onde}: {campo} vazia")
        elif c.tipo == "latencia" and tamanho(c.duracao_s) is None:
            achados.append(f"{onde}: clip de latência com {c.duracao_s} s, fora de 5, 15 ou 30 s ± {FOLGA_S}")

    enunciados = [c for c in lista if c.tipo == "enunciado"]
    falantes = {c.falante_id for c in enunciados}
    if len(falantes) < FALANTES_MIN:
        achados.append(f"quota: {len(falantes)} falantes, mínimo {FALANTES_MIN}")
    if len(enunciados) < ENUNCIADOS_MIN:
        achados.append(f"quota: {len(enunciados)} enunciados, mínimo {ENUNCIADOS_MIN}")
    n = len(enunciados)
    conhecidos = [c for c in enunciados if all(e in roteiro for e in c.enunciados)]
    com_numeros = sum(1 for c in conhecidos if "numeros" in grupos(c, roteiro))
    com_linguas = sum(1 for c in conhecidos if "linguas" in grupos(c, roteiro))
    ruidosos = sum(1 for c in enunciados if c.ambiente == "ruidoso")
    for nome, parte, minimo in (
        ("com números", com_numeros, NUMEROS_MIN),
        ("com línguas nacionais ou mistura", com_linguas, LINGUAS_MIN),
        ("em ambiente ruidoso", ruidosos, RUIDO_MIN),
    ):
        if _fraccao(parte, n) < minimo:
            achados.append(f"quota: {parte} de {n} enunciados {nome}, mínimo {minimo:.0%}")

    com_refs = [c for c in enunciados if c.ref_a.strip() and c.ref_b.strip()]
    if com_refs:
        divergencia = agregar(alinhar(c.ref_a, c.ref_b) for c in com_refs).wer or 0.0
        if Decimal(str(divergencia)) > DIVERGENCIA_MAX:
            achados.append(f"anotadores: divergência {divergencia:.2%} antes de reconciliar, máximo {DIVERGENCIA_MAX:.0%}")
    return achados


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("uso: python manifesto.py MANIFESTO.csv", file=sys.stderr)
        return 2
    try:
        achados = verificar(ler(args[0]), ler_roteiro())
    except (OSError, ManifestoInvalido) as exc:
        print(f"manifesto ilegível: {exc}", file=sys.stderr)
        return 2
    for a in achados:
        print(a)
    print(f"manifesto: {len(achados)} achados")
    return 1 if achados else 0


if __name__ == "__main__":
    raise SystemExit(main())
