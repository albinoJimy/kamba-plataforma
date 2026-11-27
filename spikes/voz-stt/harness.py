"""O *harness* do spike de voz: chama um STT por cada clip e regista (KAM-107).

    python harness.py correr --manifesto M.csv --audio PASTA --destino R.jsonl \\
        --fornecedor groq --autorizacao A.json [--tipo enunciado|latencia] \\
        [--repeticoes N] [--tecto-s 30]

Uma linha JSON por execução, **acrescentada** ao destino:

    clip_id, tipo, fornecedor, modelo, inicio_utc, latencia_ms, estado,
    hipotese, confianca, duracao_s, regras

O que **não** vai para a linha: o `falante_id`, o caminho do ficheiro e o
áudio. O relatório junta o falante pelo manifesto quando precisa dele, que é só
para contar, e o relatório não o escreve.

Três portas fechadas antes do primeiro envio, todas por ensaio:

1. A `Autorizacao` (consentimentos, X1, retenção e não-treino) para os falantes
   **deste** manifesto e **este** fornecedor.
2. A chave do cofre no ambiente, nunca num ficheiro.
3. O áudio e o destino **fora** do repositório: o áudio é de pessoas, e as
   hipóteses são transcrições da voz delas.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

from autorizacao import Autorizacao, EnvioRecusado
from manifesto import Clip, ManifestoInvalido, ler
from normalizar import VERSAO_DAS_REGRAS
from porta import ErroStt, SttProvider

AQUI = Path(__file__).resolve().parent
RAIZ_DO_REPOSITORIO = AQUI.parents[1]
MIME = "audio/ogg"
IDIOMA = "pt"


class DentroDoRepositorio(PermissionError):
    pass


def exigir_fora_do_repositorio(caminho: Path, raiz: Path = RAIZ_DO_REPOSITORIO) -> None:
    """Recusa este repositório **e qualquer outro**: um caminho com um `.git` acima.

    Só a raiz deste *worktree* deixava passar o *checkout* principal e os
    *worktrees* irmãos, que são o mesmo repositório público noutra pasta.
    """
    resolvido = caminho.resolve()
    if resolvido == raiz or raiz in resolvido.parents or any(
        (p / ".git").exists() for p in (resolvido, *resolvido.parents)
    ):
        raise DentroDoRepositorio(
            f"{caminho} está dentro de um repositório git: áudio, transcrições e autorizações ficam fora dele"
        )


def exigir_ficheiros_do_falante(clips: Iterable[Clip], pasta_audio: Path) -> None:
    """Antes do primeiro envio: cada ficheiro fica na pasta, e na pasta do seu falante.

    A autorização confere os pseudónimos da coluna `falante_id`; sem isto, um
    `ficheiro` com `..` ou apontado para a pasta de outro falante enviava a voz
    de quem a autorização nunca viu.
    """
    raiz = pasta_audio.resolve()
    for c in clips:
        alvo = (pasta_audio / c.ficheiro).resolve()
        if (raiz / c.falante_id) not in alvo.parents or ".." in Path(c.ficheiro).parts or Path(c.ficheiro).is_absolute():
            raise ManifestoInvalido(f"{c.clip_id}: o ficheiro tem de estar em <audio>/{c.falante_id}/")


def agora_utc() -> datetime:
    return datetime.now(timezone.utc)


def correr(
    clips: Iterable[Clip],
    pasta_audio: Path,
    stt: SttProvider,
    destino: Path,
    *,
    repeticoes: int = 1,
    tecto_s: float = 30.0,
    relogio: Callable[[], float] = time.monotonic,
    agora: Callable[[], datetime] = agora_utc,
) -> int:
    """Corre e acrescenta ao destino. Devolve o número de execuções escritas."""
    clips = list(clips)
    exigir_fora_do_repositorio(pasta_audio)
    exigir_fora_do_repositorio(destino)
    exigir_ficheiros_do_falante(clips, pasta_audio)
    if repeticoes < 1:
        raise ValueError("repeticoes >= 1")
    escritas = 0
    with open(destino, "a", encoding="utf-8") as saida:
        for clip in clips:
            audio = (pasta_audio / clip.ficheiro).read_bytes()
            for _ in range(repeticoes):
                inicio = agora()
                t0 = relogio()
                hipotese: str | None = None
                confianca: float | None = None
                try:
                    t = stt.transcrever(audio, mime=MIME, idioma=IDIOMA, tecto_s=tecto_s)
                    estado = "ok"
                    hipotese, confianca = t.texto, t.confianca
                except ErroStt as exc:
                    estado = exc.tipo
                latencia_ms = round((relogio() - t0) * 1000, 1)
                linha = {
                    "clip_id": clip.clip_id,
                    "tipo": clip.tipo,
                    "fornecedor": stt.nome,
                    "modelo": stt.modelo,
                    "inicio_utc": inicio.astimezone(timezone.utc).isoformat(),
                    "latencia_ms": latencia_ms,
                    "estado": estado,
                    "hipotese": hipotese,
                    "confianca": confianca,
                    "duracao_s": str(clip.duracao_s),
                    "regras": VERSAO_DAS_REGRAS,
                }
                saida.write(json.dumps(linha, ensure_ascii=False) + "\n")
                saida.flush()
                escritas += 1
    return escritas


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="harness.py")
    sub = p.add_subparsers(dest="comando", required=True)
    c = sub.add_parser("correr")
    c.add_argument("--manifesto", required=True, type=Path)
    c.add_argument("--audio", required=True, type=Path)
    c.add_argument("--destino", required=True, type=Path)
    c.add_argument("--fornecedor", required=True, choices=("groq", "openai"))
    c.add_argument("--autorizacao", required=True, type=Path)
    c.add_argument("--tipo", choices=("enunciado", "latencia"), default="enunciado")
    c.add_argument("--repeticoes", type=int, default=1)
    c.add_argument("--tecto-s", type=float, default=30.0)
    a = p.parse_args(argv)

    from fornecedores import construir

    try:
        for caminho in (a.manifesto, a.autorizacao):
            exigir_fora_do_repositorio(caminho)
        clips = [x for x in ler(a.manifesto) if x.tipo == a.tipo]
        stt = construir(a.fornecedor, Autorizacao.ler(a.autorizacao), {x.falante_id for x in clips})
        n = correr(clips, a.audio, stt, a.destino, repeticoes=a.repeticoes, tecto_s=a.tecto_s)
    except (EnvioRecusado, DentroDoRepositorio, ManifestoInvalido) as exc:
        print(f"recusado: {exc}", file=sys.stderr)
        return 1
    print(f"harness: {n} execuções escritas em {a.destino}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
