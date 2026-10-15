#!/usr/bin/env python3
"""Suite de contrato do `StorageProvider` contra um SeaweedFS descartavel (KAM-011).

    python infra/storage/contrato.py            # ou: make storage-contrato

O que faz, por esta ordem:

1. gera um par de credenciais de teste e escolhe uma porta livre em 127.0.0.1;
2. levanta `infra/compose/docker-compose.storage.yml` (SeaweedFS 4.48, fixado
   por *digest*, dados em `tmpfs`);
3. espera que o gateway S3 aceite um pedido **assinado**;
4. corre, contra esse servidor: a escrita de interoperabilidade do lado Python,
   a suite TypeScript (bateria de contrato + testes de capacidade) e a suite
   Python (bateria de contrato + leitura de interoperabilidade);
5. apaga o contentor, corra o que correr.

So biblioteca padrao, e nao precisa do `.venv`: o `kamba_core` nao tem
dependencias.

**Isto nao e um *gate* de CI.** O ticket nao pede um, e o *gate* 5 (integracao)
continua reservado. Corre-se a mao, quando se mexe em `storage/`, e o resultado
de uma execucao esta em `docs/evidencia/KAM-011-seaweedfs.md`. O que corre no
*gate* 4 e a mesma bateria sobre o *fake* e sobre um servidor S3 em memoria.

As credenciais passam pelo ambiente, nunca pela linha de comandos, e nao sao
escritas em ficheiro nenhum.
"""

from __future__ import annotations

import argparse
import os
import secrets as _aleatorio
import shutil
import socket
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent.parent
COMPOSE = RAIZ / "infra" / "compose" / "docker-compose.storage.yml"
PY_SRC = RAIZ / "libs" / "py-core" / "src"
PY_TESTES = RAIZ / "libs" / "py-core" / "tests" / "integracao"
TS_PACOTE = RAIZ / "packages" / "core-ts"
TS_SUITE = "tests/integracao/storage.s3real.test.ts"

#: Imagem em que a suite TypeScript corre quando a maquina nao tem `node`. E a
#: dos `Dockerfile` dos servicos, fixada por digest e declarada em
#: `ci/supply-chain/imagens.yaml` (`fontes_adicionais`): `make supply-chain`
#: falha se o digest daqui deixar de ser o do inventario (KAM-067).
IMAGEM_NODE = (
    "node:24.21.0-trixie-slim"
    "@sha256:173f125896c3b47ddf056734c7ea789d04595a6a08769a8f78e0df642781fb66"
)

#: As duas variaveis de segredo, pelo nome que o `EnvSecretProvider` le.
SEGREDOS = ("KAMBA_SECRET_STORAGE_ACCESS_KEY_ID", "KAMBA_SECRET_STORAGE_SECRET_ACCESS_KEY")

BUCKET = "kamba-contrato"
REGIAO = "us-east-1"

sys.path.insert(0, str(PY_SRC))


def porta_livre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def esperar_pelo_s3(endpoint: str, ambiente: dict[str, str], limite_s: float) -> None:
    """Espera ate o gateway aceitar um pedido assinado (criar o *bucket*)."""
    from kamba_core.storage.s3 import PedidoHttp, transporte_por_http
    from kamba_core.storage.sigv4 import Credenciais, assinar_pedido

    credenciais = Credenciais(
        ambiente["KAMBA_SECRET_STORAGE_ACCESS_KEY_ID"],
        ambiente["KAMBA_SECRET_STORAGE_SECRET_ACCESS_KEY"],
    )
    url = f"{endpoint}/{BUCKET}"
    fim = time.monotonic() + limite_s
    ultimo = "sem resposta"
    while time.monotonic() < fim:
        cabecalhos = assinar_pedido(
            metodo="PUT",
            url=url,
            credenciais=credenciais,
            regiao=REGIAO,
            agora=datetime.now(UTC),
        )
        del cabecalhos["host"]
        try:
            resposta = transporte_por_http(5)(PedidoHttp("PUT", url, cabecalhos, b""))
            b"".join(resposta.corpo)
            if resposta.estado in (200, 409):
                return
            ultimo = f"HTTP {resposta.estado}"
        except OSError as erro:
            ultimo = type(erro).__name__
        time.sleep(1)
    raise SystemExit(f"o gateway S3 nao ficou pronto em {limite_s:.0f} s ({ultimo})")


def correr(titulo: str, comando: list[str], ambiente: dict[str, str], cwd: Path) -> bool:
    print(f"\n==> {titulo}", flush=True)
    return subprocess.run(comando, env=ambiente, cwd=cwd, check=False).returncode == 0


def comando_ts(endpoint_no_host: str, porta: int, ambiente: dict[str, str]) -> tuple[list[str], dict[str, str]]:
    """O comando da suite TypeScript: `node` da maquina, ou um contentor."""
    if shutil.which("node"):
        return ["node", "--test", TS_SUITE], {**ambiente, "KAMBA_STORAGE_ENDPOINT": endpoint_no_host}
    # Dentro de um contentor, o servidor publicado em 127.0.0.1 do anfitriao
    # chama-se `host.docker.internal`. As variaveis passam por nome (`-e NOME`),
    # para o valor nao aparecer na linha de comandos.
    passadas = sorted(
        n for n in ambiente if n.startswith("KAMBA_STORAGE_") or n in (*SEGREDOS, "KAMBA_ENV")
    )
    comando = [
        "docker", "run", "--rm",
        "--add-host", "host.docker.internal:host-gateway",
        "-v", f"{RAIZ}:/repo:ro",
        "-w", "/repo/packages/core-ts",
    ]  # fmt: skip
    for nome in passadas:
        comando += ["-e", nome]
    comando += [IMAGEM_NODE, "node", "--test", TS_SUITE]
    return comando, {
        **ambiente,
        "KAMBA_STORAGE_ENDPOINT": f"http://host.docker.internal:{porta}",
        # O Git Bash do Windows reescreve argumentos que parecem caminhos.
        "MSYS_NO_PATHCONV": "1",
    }


def main() -> int:
    analisador = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    analisador.add_argument("--manter", action="store_true", help="nao apaga o contentor no fim")
    analisador.add_argument("--so", choices=("ts", "py"), help="corre so uma das duas suites")
    opcoes = analisador.parse_args()

    if shutil.which("docker") is None:
        raise SystemExit("FALTA docker: a suite levanta um SeaweedFS num contentor.")

    porta = porta_livre()
    endpoint = f"http://127.0.0.1:{porta}"
    projecto = f"kamba-storage-contrato-{os.getpid()}"
    ambiente = {
        **os.environ,
        "KAMBA_ENV": "dev",
        "KAMBA_STORAGE_PORT": str(porta),
        "KAMBA_STORAGE_ENDPOINT": endpoint,
        "KAMBA_STORAGE_BUCKET": BUCKET,
        "KAMBA_STORAGE_REGION": REGIAO,
        "KAMBA_STORAGE_DESTINO_COUNTRY": "AO",
        "KAMBA_STORAGE_DESTINO_PROVIDER": "seaweedfs_contrato",
        "KAMBA_SECRET_STORAGE_ACCESS_KEY_ID": f"kamba-contrato-{_aleatorio.token_hex(4)}",
        "KAMBA_SECRET_STORAGE_SECRET_ACCESS_KEY": _aleatorio.token_hex(24),
        "PYTHONPATH": str(PY_SRC),
    }
    compose = ["docker", "compose", "-p", projecto, "-f", str(COMPOSE)]

    print(f"==> SeaweedFS descartavel em {endpoint} (projecto {projecto})", flush=True)
    resultados: dict[str, bool] = {}
    try:
        subprocess.run([*compose, "up", "--detach", "--wait"], env=ambiente, check=True)
        esperar_pelo_s3(endpoint, ambiente, 120)

        python = [sys.executable, "-m", "unittest", "discover", "-s", str(PY_TESTES), "-t", str(PY_TESTES)]
        if opcoes.so != "ts":
            resultados["interoperabilidade: Python escreve"] = correr(
                "Python escreve o objecto de interoperabilidade",
                [*python, "-k", "InteropEscreve"],
                ambiente,
                RAIZ,
            )
        if opcoes.so != "py":
            comando, ambiente_ts = comando_ts(endpoint, porta, ambiente)
            resultados["suite TypeScript"] = correr(
                "suite TypeScript: bateria de contrato e testes de capacidade",
                comando,
                ambiente_ts,
                TS_PACOTE,
            )
        if opcoes.so != "ts":
            selector = ["-k", "ContratoNoServidorReal", "-k", "AAssinaturaEVerificada"]
            if opcoes.so is None:
                selector += ["-k", "InteropLe"]
            resultados["suite Python"] = correr(
                "suite Python: bateria de contrato",
                [*python, "-v", *selector],
                ambiente,
                RAIZ,
            )
    finally:
        if opcoes.manter:
            print(f"\n(contentor mantido; para o apagar: docker compose -p {projecto} down -v)")
        else:
            subprocess.run(
                [*compose, "down", "--volumes", "--timeout", "5"],
                env=ambiente,
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

    print("\n==> resultado")
    for nome, passou in resultados.items():
        print(f"    {'verde   ' if passou else 'VERMELHO'} {nome}")
    if not resultados or not all(resultados.values()):
        print("\nstorage-contrato: VERMELHO.")
        return 1
    print("\nstorage-contrato: verde.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
