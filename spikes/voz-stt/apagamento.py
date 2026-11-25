"""O apagamento do áudio do spike de voz (KAM-107, critério 2).

    python apagamento.py verificar --manifesto M.csv --audio PASTA R1.jsonl [R2.jsonl ...]
    python apagamento.py apagar    --manifesto M.csv --audio PASTA --confirmo

A letra: «áudio apagado do nosso armazenamento ≤ 24 h após transcrever e no fim
do spike». O `verificar` dá um achado por cada ficheiro que **ainda existe** mais
de 24 h depois da primeira transcrição bem sucedida do seu clip, por qualquer dos
fornecedores; sai com 1 se houver algum. O `apagar` apaga **só** os ficheiros que
o manifesto nomeia — nunca a pasta inteira, nunca um ficheiro que o manifesto não
liste — e diz quantos apagou e quantos já não existiam.

**O bloco não fixa prazo entre gravar e transcrever**, e este módulo não inventa
um: o áudio tem de existir enquanto os anotadores o ouvem, e quanto tempo isso
pode durar é uma regra de retenção que fica devolvida no `H7_Voz_STT.md` §8.

O que isto não vê: cópias fora da pasta (o telemóvel ou o gravador de quem
gravou, uma partilha, uma cópia de segurança). O protocolo de gravação manda
apagá-las à mão e registá-lo; nenhum *script* o prova.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Mapping

from harness import exigir_fora_do_repositorio
from latencia import ler_resultados
from manifesto import Clip, ler

PRAZO = timedelta(hours=24)


def primeira_transcricao(resultados: Iterable[Mapping]) -> dict[str, datetime]:
    primeiro: dict[str, datetime] = {}
    for r in resultados:
        if r.get("estado") != "ok":
            continue
        quando = datetime.fromisoformat(r["inicio_utc"])
        clip = r["clip_id"]
        if clip not in primeiro or quando < primeiro[clip]:
            primeiro[clip] = quando
    return primeiro


def atrasados(clips: Iterable[Clip], pasta: Path, resultados: Iterable[Mapping], agora: datetime) -> list[str]:
    exigir_fora_do_repositorio(pasta)
    primeiro = primeira_transcricao(resultados)
    achados = []
    for c in clips:
        quando = primeiro.get(c.clip_id)
        if quando is not None and agora - quando > PRAZO and (pasta / c.ficheiro).exists():
            horas = (agora - quando).total_seconds() / 3600
            achados.append(f"{c.clip_id}: áudio ainda existe {horas:.1f} h depois de transcrito")
    return achados


def apagar(clips: Iterable[Clip], pasta: Path) -> tuple[int, int]:
    exigir_fora_do_repositorio(pasta)
    raiz = pasta.resolve()
    apagados = ausentes = 0
    for c in clips:
        alvo = (pasta / c.ficheiro).resolve()
        if raiz not in alvo.parents:
            raise PermissionError(f"{c.clip_id}: o ficheiro sai da pasta do áudio")
        if alvo.exists():
            alvo.unlink()
            apagados += 1
        else:
            ausentes += 1
    return apagados, ausentes


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="apagamento.py")
    sub = p.add_subparsers(dest="comando", required=True)
    v = sub.add_parser("verificar")
    v.add_argument("--manifesto", required=True, type=Path)
    v.add_argument("--audio", required=True, type=Path)
    v.add_argument("resultados", nargs="+", type=Path)
    a = sub.add_parser("apagar")
    a.add_argument("--manifesto", required=True, type=Path)
    a.add_argument("--audio", required=True, type=Path)
    a.add_argument("--confirmo", action="store_true")
    args = p.parse_args(argv)
    clips = ler(args.manifesto)
    if args.comando == "verificar":
        achados = atrasados(clips, args.audio, ler_resultados(args.resultados), datetime.now(timezone.utc))
        for x in achados:
            print(x)
        print(f"apagamento: {len(achados)} ficheiros fora do prazo de 24 h")
        return 1 if achados else 0
    if not args.confirmo:
        print("recusado: apagar exige --confirmo", file=sys.stderr)
        return 2
    apagados, ausentes = apagar(clips, args.audio)
    print(f"apagamento: {apagados} apagados, {ausentes} já não existiam, de {len(clips)} no manifesto")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
