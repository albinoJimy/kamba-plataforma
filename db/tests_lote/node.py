"""Como correr o Node, a partir da suite do processo de lote do onboarding (KAM-198).

O ensaio contra a base e TypeScript e vive em
`packages/core-ts/tests_bd/lote.bd.test.ts`. Esta suite, em Python, e o que o poe
a correr contra a base descartavel que `db/gate_bd.py --suite tests_lote`
levanta — com os papeis criados e as migracoes em `head` — e e ela que le o que
ele deixa: a saida e os testes que correram pelo nome.

E a forma do `db/tests_avisos/node.py`, com uma diferenca que se paga: o ensaio
importa o `services/onboarding-web/src/lote/processo.ts`, que resolve o `pg`, o
`hono` e o `@kamba/core-ts` pelos `node_modules` **do servico**. Por isso, quando
os modulos vivem noutra raiz (a prova por mutacao), liga-se tambem o
`services/onboarding-web/node_modules`.

Sao tres senhas: o administrador (as sementes), o `kamba_batch` (a fila) e o
`kamba_app` (o screening, dentro do tenant do caso).
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

#: Segundos. O ensaio corre dez cenarios, um deles com duas rondas de vinte
#: aberturas concorrentes e outro que arranca o processo inteiro (que numa montagem do Windows
#: leva ~40 s so a carregar). Medido: ~110 s sem o arranque. Folga para um
#: runner lento, nao alvo.
TEMPO_MAXIMO = 600

#: O codigo de saida de um ensaio que estourou o tempo. 124 e o do `timeout(1)`,
#: e usa-se o mesmo para que quem leia o registo o reconheca.
CODIGO_DE_TEMPO = 124

#: Onde vivem os `node_modules`, quando nao e na raiz do codigo que se testa (a
#: prova por mutacao corre sobre uma copia que nao os leva).
VARIAVEL_DOS_MODULOS = "KAMBA_RAIZ_NODE_MODULES"

#: O que os testes em Node precisam de saber do ambiente. So nomes: os valores
#: passam pelo ambiente do processo, nunca pela linha de comandos.
#:
#: Quatro, e nao as cinco do CHR: o `kamba_resolver` e o `kamba_identity` nao
#: entram, porque este modulo nao resolve canal nenhum nem toca em identidade de
#: contacto — entra-se sempre pelo `tenant_id`.
VARIAVEIS = (
    "KAMBA_DB_NAME",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "KAMBA_SECRET_DB_APP_PASSWORD",
    "KAMBA_SECRET_DB_BATCH_PASSWORD",
)

#: Os `node_modules` que o ensaio resolve: o da raiz, o do pacote e o do
#: servico cujo processo ele monta.
MODULOS = ("node_modules", "packages/core-ts/node_modules", "services/onboarding-web/node_modules")

VARIAVEL_DO_CONTENTOR = "KAMBA_GATE_CONTENTOR"


class SemContentor(RuntimeError):
    """Nao se sabe em que contentor esta o PostgreSQL."""


def contentor() -> str:
    nome = os.environ.get(VARIAVEL_DO_CONTENTOR, "")
    if not nome:
        raise SemContentor(
            f"{VARIAVEL_DO_CONTENTOR} nao esta definida. Sem `node` no PATH, a "
            "suite do lote corre na rede do contentor do PostgreSQL; "
            "`python db/gate_bd.py --suite tests_lote` define-a."
        )
    return nome


def _raiz_dos_modulos() -> Path:
    return Path(os.environ.get(VARIAVEL_DOS_MODULOS) or RAIZ)


def _ligar_modulos() -> None:
    """Com `node` no `PATH` e os modulos noutra raiz, liga-os por atalho simbolico."""
    origem = _raiz_dos_modulos()
    if origem == RAIZ:
        return
    for relativo in MODULOS:
        destino = RAIZ / relativo
        if not destino.exists():
            destino.symlink_to(origem / relativo, target_is_directory=True)


def _correr(comando: list[str], ambiente: dict, cwd: Path | None) -> subprocess.CompletedProcess:
    """Corre o comando e, se o tempo estourar, **devolve o que ele ja escreveu**.

    Sem isto, um ensaio pendurado levanta `TimeoutExpired` e a saida parcial
    morre com a excepcao: quem investiga fica com zero linhas e o nome do
    comando. E o `TimeoutExpired` traz o que foi capturado nos campos `stdout` e
    `stderr`, pelo que basta converte-lo num `CompletedProcess` — e a suite, que
    ja sabe ler falhas do TAP, mostra onde e que o ensaio parou.
    """
    try:
        return subprocess.run(
            comando,
            cwd=cwd,
            env=ambiente,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=TEMPO_MAXIMO,
        )
    except subprocess.TimeoutExpired as estouro:
        def texto(valor) -> str:
            if valor is None:
                return ""
            return valor if isinstance(valor, str) else valor.decode("utf-8", "replace")

        return subprocess.CompletedProcess(
            comando,
            CODIGO_DE_TEMPO,
            texto(estouro.stdout),
            texto(estouro.stderr)
            + f"\n[tempo] o ensaio passou dos {TEMPO_MAXIMO} s e foi interrompido\n",
        )


def correr(argumentos: list[str], saida: Path) -> subprocess.CompletedProcess:
    """Corre `node <argumentos>` em `packages/core-ts`. `saida` e onde ele escreve."""
    ambiente = dict(os.environ)
    if shutil.which("node"):
        _ligar_modulos()
        comando = ["node", *[a.replace("{saida}", str(saida)) for a in argumentos]]
        return _correr(comando, ambiente, PACOTE)

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
        for relativo in MODULOS:
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
    return _correr(comando, ambiente, None)
