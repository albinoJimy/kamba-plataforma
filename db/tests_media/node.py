"""Como correr o Node, a partir da suite da midia (KAM-020).

Os testes da midia contra a base sao TypeScript e vivem em
`packages/core-ts/tests_bd/media.bd.test.ts`. Esta suite, em Python, e o que os
poe a correr contra a base descartavel que
`db/gate_bd.py --suite tests_media` levanta — com os papeis criados e as
migracoes em `head` — e e ela que le o que eles deixam: a saida e a cobertura de
`src/med/`.

E a mesma mecanica do `db/tests_handoff/node.py`, e as diferencas do handoff
valem todas aqui pela mesma razao:

* **nao leva o `tools/meta-sim`.** A saida de canal precisava dele para contar
  chamadas HTTP com o `GraphFalso`; a midia fala com a Meta mas por **porta** —
  o `ClienteDeMidia` tem duas operacoes e o cliente falso vive no proprio
  ensaio. E a razao de ser porta e que **a API de midia da Meta nao tem
  evidencia nenhuma** no `E1`: um simulador dela seria uma invencao a fingir
  medicao, e o simulador do KAM-024 nao a cobre (o `id` que ele poe no webhook
  nao e servivel pelos endpoints de midia);
* **o tempo maximo e o mesmo.** O ensaio de base abre duas ligacoes, faz um
  punhado de descargas e uma corrida concorrente; nao ha carga. 600 e folga
  larga, e a razao de nao ser menos e a que a saida pagou: um tecto que corta
  no limite nao distingue «o ensaio esta lento» de «o ensaio esta pendurado».

Onde corre: com `node` no `PATH` (o CI tem-no; a accao `preparar` instala-o).
Sem `node` — o caso de uma maquina de desenvolvimento em Windows — corre-se a
imagem oficial **na rede do contentor do PostgreSQL**, para que a base esteja em
`127.0.0.1:5432` sem publicar mais nada.
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
#: `ci/supply-chain/imagens.yaml` registra para ela (KAM-067).
IMAGEM_NODE = (
    "node:24.21.0-trixie-slim"
    "@sha256:173f125896c3b47ddf056734c7ea789d04595a6a08769a8f78e0df642781fb66"
)

#: Segundos. Folga para um runner lento, nao alvo.
#:
#: O ensaio de base abre duas ligacoes e faz um punhado de aberturas e fechos:
#: nao ha carga nem mil insercoes, e mediu-se em cerca de 30 s. 600 e folga
#: larga, e a razao de nao ser menos e a mesma que a suite da saida pagou — um
#: tecto que corta no limite nao distingue «o ensaio esta lento» de «o ensaio
#: esta pendurado».
TEMPO_MAXIMO = 600

#: Onde vivem os `node_modules`, quando nao e na raiz do codigo que se testa (a
#: prova por mutacao corre sobre uma copia que nao os leva).
VARIAVEL_DOS_MODULOS = "KAMBA_RAIZ_NODE_MODULES"

#: O que os testes em Node precisam de saber do ambiente. So nomes: os valores
#: passam pelo ambiente do processo, nunca pela linha de comandos.
#:
#: Sao **cinco** senhas e nao quatro: o CHR e o primeiro modulo que precisa do
#: `kamba_resolver`, porque e o unico papel que responde
#: `phone_number_id -> tenant` antes de haver contexto.
VARIAVEIS = (
    "KAMBA_DB_NAME",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "KAMBA_SECRET_DB_RESOLVER_PASSWORD",
    "KAMBA_SECRET_DB_IDENTITY_PASSWORD",
    "KAMBA_SECRET_DB_APP_PASSWORD",
    "KAMBA_SECRET_DB_BATCH_PASSWORD",
)

VARIAVEL_DO_CONTENTOR = "KAMBA_GATE_CONTENTOR"

#: As pastas de `node_modules` a ligar quando os modulos vivem noutra raiz.
#:
#: **Duas e nao tres**, ao contrario da suite da saida: ela monta tambem o
#: `tools/meta-sim`, porque precisa do `GraphFalso` para contar chamadas HTTP a
#: Meta. A midia fala com a Meta mas por porta, e o cliente falso vive no
#: proprio ensaio — ver a nota do modulo para a razao de nao haver simulador.
PASTAS_DE_MODULOS = (
    "node_modules",
    "packages/core-ts/node_modules",
)


class SemContentor(RuntimeError):
    """Nao se sabe em que contentor esta o PostgreSQL."""


def contentor() -> str:
    nome = os.environ.get(VARIAVEL_DO_CONTENTOR, "")
    if not nome:
        raise SemContentor(
            f"{VARIAVEL_DO_CONTENTOR} nao esta definida. Sem `node` no PATH, a "
            "suite da **midia** corre na rede do contentor do PostgreSQL; "
            "`python db/gate_bd.py --suite tests_media` define-a. "
            "(A mensagem anterior desta excepcao dizia «a suite da saida», "
            "residuo da copia do `tests_outbound` que o KAM-019 herdou e o "
            "KAM-020 corrigiu nos dois sitios.)"
        )
    return nome


def _raiz_dos_modulos() -> Path:
    return Path(os.environ.get(VARIAVEL_DOS_MODULOS) or RAIZ)


def _ligar_modulos() -> None:
    """Com `node` no `PATH` e os modulos noutra raiz, liga-os por atalho simbolico."""
    origem = _raiz_dos_modulos()
    if origem == RAIZ:
        return
    for relativo in PASTAS_DE_MODULOS:
        destino = RAIZ / relativo
        if not destino.exists():
            destino.symlink_to(origem / relativo, target_is_directory=True)


def correr(argumentos: list[str], saida: Path) -> subprocess.CompletedProcess:
    """Corre `node <argumentos>` em `packages/core-ts`. `saida` e onde ele escreve."""
    ambiente = dict(os.environ)
    if shutil.which("node"):
        _ligar_modulos()
        comando = ["node", *[a.replace("{saida}", str(saida)) for a in argumentos]]
        return subprocess.run(
            comando,
            cwd=PACOTE,
            env=ambiente,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=TEMPO_MAXIMO,
        )

    # Sem `node`: a imagem oficial, na rede do contentor da base.
    ambiente.update({"KAMBA_DB_HOST": "127.0.0.1", "KAMBA_DB_PORT": "5432"})
    comando = [
        "docker",
        "run",
        "--rm",
        "--network",
        f"container:{contentor()}",
        "--volume",
        f"{RAIZ}:/repo:ro",
        "--volume",
        f"{saida.parent}:/saida",
        "--workdir",
        "/repo/packages/core-ts",
    ]
    modulos = _raiz_dos_modulos()
    if modulos != RAIZ:
        for relativo in PASTAS_DE_MODULOS:
            (RAIZ / relativo).mkdir(parents=True, exist_ok=True)
            comando += ["--volume", f"{modulos / relativo}:/repo/{relativo}:ro"]
    for nome in (*VARIAVEIS, "KAMBA_DB_HOST", "KAMBA_DB_PORT"):
        comando += ["--env", nome]
    comando += [
        IMAGEM_NODE,
        "node",
        *[a.replace("{saida}", f"/saida/{saida.name}") for a in argumentos],
    ]
    # `MSYS_NO_PATHCONV`: no Git Bash do Windows, sem isto, `/repo` e `/saida`
    # eram reescritos para caminhos do Windows antes de chegarem ao Docker.
    ambiente["MSYS_NO_PATHCONV"] = "1"
    return subprocess.run(
        comando,
        env=ambiente,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=TEMPO_MAXIMO,
    )
