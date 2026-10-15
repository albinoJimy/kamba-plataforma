"""Como correr o Node, e como falar com o PostgreSQL do gate, a partir da suite.

Os testes do modulo de identidade sao TypeScript e precisam de tres coisas que
esta suite, em Python, lhes arranja:

    node        no `PATH` (o CI tem-no: a accao `preparar` instala-o). Sem ele —
                e o caso de uma maquina de desenvolvimento em Windows — corre-se
                a imagem oficial, **na rede do contentor do PostgreSQL**, para
                que a base esteja em `127.0.0.1:5432` sem publicar mais nada.
    pg_dump     o do proprio contentor (`docker exec`): e a mesma versao do
                servidor, e nao exige instalar um cliente no runner.
    o registo   `docker logs` do contentor, que e para onde a imagem manda o
                registo do servidor.

O nome do contentor chega em `KAMBA_GATE_CONTENTOR`, posto por `gate_bd.py`.
Sem ele nao ha *dump* nem registo, e a suite **falha** em vez de saltar: num
gate, saltar e falhar.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
PACOTE = RAIZ / "packages" / "core-ts"

#: A imagem usada quando nao ha `node` no `PATH`. A mesma versao de
#: `.node-version` (conferido por teste), fixada pelo digest que
#: `ci/supply-chain/imagens.yaml` regista para ela (KAM-067): o gate 11 confere
#: esta constante contra esse inventario.
IMAGEM_NODE = (
    "node:24.21.0-trixie-slim"
    "@sha256:173f125896c3b47ddf056734c7ea789d04595a6a08769a8f78e0df642781fb66"
)

#: Segundos. O ensaio faz mais de trinta mil resolucoes contra a base; isto e
#: folga para um runner lento, nao alvo.
TEMPO_MAXIMO = 480

VARIAVEL_DO_CONTENTOR = "KAMBA_GATE_CONTENTOR"
#: Onde vivem os `node_modules`, quando nao e na raiz do codigo que se testa
#: (a prova por mutacao corre sobre uma copia que nao os leva).
VARIAVEL_DOS_MODULOS = "KAMBA_RAIZ_NODE_MODULES"

#: O que os testes em Node precisam de saber do ambiente. So nomes: os valores
#: passam pelo ambiente do processo, nunca pela linha de comandos.
VARIAVEIS = (
    "KAMBA_DB_NAME",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "KAMBA_SECRET_DB_IDENTITY_PASSWORD",
    "KAMBA_SECRET_DB_APP_PASSWORD",
    "KAMBA_SECRET_DB_BATCH_PASSWORD",
)


class SemContentor(RuntimeError):
    """Nao se sabe em que contentor esta o PostgreSQL."""


def contentor() -> str:
    nome = os.environ.get(VARIAVEL_DO_CONTENTOR, "")
    if not nome:
        raise SemContentor(
            f"{VARIAVEL_DO_CONTENTOR} nao esta definida. A suite de identidade le o "
            "*dump* e o registo do servidor pelo contentor do PostgreSQL; "
            "`python db/gate_bd.py --suite tests_identidade` define-a."
        )
    return nome


def _raiz_dos_modulos() -> Path:
    return Path(os.environ.get(VARIAVEL_DOS_MODULOS) or RAIZ)


def _ligar_modulos() -> None:
    """Com `node` no `PATH` e os modulos noutra raiz, liga-os por atalho simbolico."""
    origem = _raiz_dos_modulos()
    if origem == RAIZ:
        return
    for relativo in ("node_modules", "packages/core-ts/node_modules"):
        destino = RAIZ / relativo
        if not destino.exists():
            destino.symlink_to(origem / relativo, target_is_directory=True)


def correr(argumentos: list[str], saida: Path) -> subprocess.CompletedProcess:
    """Corre `node <argumentos>` em `packages/core-ts`. `saida` e onde ele escreve."""
    ambiente = dict(os.environ)
    if shutil.which("node"):
        _ligar_modulos()
        ambiente["KAMBA_IDENTIDADE_SAIDA"] = str(saida)
        comando = ["node", *[a.replace("{saida}", str(saida)) for a in argumentos]]
        return subprocess.run(
            comando, cwd=PACOTE, env=ambiente, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=TEMPO_MAXIMO,
        )

    # Sem `node`: a imagem oficial, na rede do contentor da base.
    ambiente.update(
        {
            "KAMBA_DB_HOST": "127.0.0.1",
            "KAMBA_DB_PORT": "5432",
            "KAMBA_IDENTIDADE_SAIDA": "/saida",
        }
    )
    comando = [
        "docker", "run", "--rm",
        "--network", f"container:{contentor()}",
        "--volume", f"{RAIZ}:/repo:ro",
        "--volume", f"{saida}:/saida",
        "--workdir", "/repo/packages/core-ts",
    ]
    modulos = _raiz_dos_modulos()
    if modulos != RAIZ:
        for relativo in ("node_modules", "packages/core-ts/node_modules"):
            (RAIZ / relativo).mkdir(parents=True, exist_ok=True)
            comando += ["--volume", f"{modulos / relativo}:/repo/{relativo}:ro"]
    for nome in (*VARIAVEIS, "KAMBA_DB_HOST", "KAMBA_DB_PORT", "KAMBA_IDENTIDADE_SAIDA"):
        comando += ["--env", nome]
    comando += [IMAGEM_NODE, "node", *[a.replace("{saida}", "/saida") for a in argumentos]]
    # `MSYS_NO_PATHCONV`: no Git Bash do Windows, sem isto, `/repo` e `/saida`
    # eram reescritos para caminhos do Windows antes de chegarem ao Docker.
    ambiente["MSYS_NO_PATHCONV"] = "1"
    return subprocess.run(
        comando, env=ambiente, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=TEMPO_MAXIMO,
    )


def _docker(*argumentos: str) -> bytes:
    resultado = subprocess.run(
        ["docker", *argumentos], capture_output=True, timeout=180
    )
    if resultado.returncode != 0:
        raise RuntimeError(
            f"docker {argumentos[0]} falhou ({resultado.returncode}): "
            f"{resultado.stderr.decode('utf-8', 'replace')[-400:]}"
        )
    return resultado.stdout + resultado.stderr


def dump_completo() -> bytes:
    """`pg_dump` da base inteira, em texto, feito dentro do contentor do servidor."""
    return _docker(
        "exec", contentor(), "pg_dump",
        "--username", os.environ["POSTGRES_USER"],
        "--dbname", os.environ["KAMBA_DB_NAME"],
    )


def registo_do_servidor() -> bytes:
    """Tudo o que o PostgreSQL registou desde que o contentor arrancou."""
    return _docker("logs", contentor())
