"""Como correr o Node, a partir da suite da saida de canal (KAM-015).

Os testes da saida contra a base sao TypeScript e vivem em
`packages/core-ts/tests_bd/outbound.bd.test.ts`. Esta suite, em Python, e o que
os poe a correr contra a base descartavel que
`db/gate_bd.py --suite tests_outbound` levanta — com os papeis criados e as
migracoes em `head` — e e ela que le o que eles deixam: a saida e a cobertura de
`src/outbound/`.

E a mesma mecanica do `db/tests_chr/node.py`, com **duas diferencas**:

* precisa de menos papeis. O CHR precisa do `kamba_resolver`, porque e o unico
  que responde `phone_number_id -> tenant` antes de haver contexto; a saida
  corre toda como `kamba_app`, com o administrador a semear. O `resolver`
  continua na lista porque o `apoio.ts` o declara, e tirar uma senha da lista
  para a por de volta no proximo ticket e ruido;
* leva o `tools/meta-sim` montado. O ensaio usa o `GraphFalso` do KAM-024 para
  **contar as chamadas HTTP**, que e a metade do criterio 2 («1 chamada a API,
  servidor falso conta») que uma base nao consegue provar.

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
#: Os ficheiros de unidade levam **0,8 s** medidos; o que leva tempo e o ensaio
#: de base, que abre tres ligacoes ao PostgreSQL e faz um punhado de envios. 900
#: era o dobro do que o `tests_chr` usa, e a razao de nao ser 420 e que a
#: primeira execucao desta suite bateu nos 421 s — e um tecto que corta no
#: limite nao distingue «o ensaio esta lento» de «o ensaio esta pendurado».
#:
#: **Subiu para 1 200 no KAM-021**, e o motivo e aritmetica e nao receio: a
#: suite ganhou dois ficheiros no KAM-023 (um deles com um ciclo de 1 200
#: incrementos) e dois no KAM-021 (um deles com 200 contactos e 200 linhas de
#: saida para a letra do criterio 7), e corre com `--test-concurrency=1`, pelo
#: que os tempos somam. Com 900, a margem sobre a medicao inicial deixou de ser
#: o dobro.
TEMPO_MAXIMO = 1200

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
#: Tres e nao duas: o ensaio importa `@kamba/meta-sim` para contar as chamadas
#: HTTP com o `GraphFalso` (KAM-024), e sem a pasta do simulador o `import`
#: falha com `ERR_MODULE_NOT_FOUND` — o mesmo defeito que a copia da prova por
#: mutacao do KAM-014 pagou por lhe faltar o `packages/contracts`.
PASTAS_DE_MODULOS = (
    "node_modules",
    "packages/core-ts/node_modules",
    "tools/meta-sim/node_modules",
)


class SemContentor(RuntimeError):
    """Nao se sabe em que contentor esta o PostgreSQL."""


def contentor() -> str:
    nome = os.environ.get(VARIAVEL_DO_CONTENTOR, "")
    if not nome:
        raise SemContentor(
            f"{VARIAVEL_DO_CONTENTOR} nao esta definida. Sem `node` no PATH, a "
            "suite da saida corre na rede do contentor do PostgreSQL; "
            "`python db/gate_bd.py --suite tests_outbound` define-a."
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
