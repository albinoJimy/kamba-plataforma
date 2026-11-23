"""`python -m kamba_core.registo_pg` — o recolector do registo do PostgreSQL (KAM-225).

So ligacoes: le o ambiente, abre a pasta do registo, arranca a rota e a volta. A
decisao toda esta em `leitor.py` e `processo.py`, que se testam sem rede nem
base; este ficheiro fica fora da medicao do *gate* 4 como os outros
`__main__.py` (`ci/thresholds.yaml`).

Corre com a imagem do AGR (`services/agr/Dockerfile`), que traz o `kamba_core`
no `PYTHONPATH`, como o `idx`.

Codigos de saida: 2 configuracao ou registo ilegivel no arranque, 3 leitura
falhada a meio, 0 paragem pedida.
"""

from __future__ import annotations

import os
import signal
import sys
import threading
from pathlib import Path
from typing import Any

from kamba_core.logger import instalar

from .processo import (
    PASTA_POR_OMISSAO,
    SERVICO,
    VARIAVEL_DA_PASTA,
    Recolha,
    RegistoIlegivel,
    correr_ate,
    porta,
    servidor,
)


def main(ambiente: Any = None) -> int:
    ambiente = os.environ if ambiente is None else ambiente
    log = instalar(SERVICO)
    try:
        numero = porta(ambiente)
        recolha = Recolha(Path(ambiente.get(VARIAVEL_DA_PASTA) or PASTA_POR_OMISSAO))
    except (ValueError, RegistoIlegivel) as exc:
        log.excepcao(exc, "arranque_invalido")
        return 2

    http = servidor(numero, anfitriao=ambiente.get("HOST", "127.0.0.1"))
    rota = threading.Thread(target=http.serve_forever, name="registo-pg-http", daemon=True)
    parar = threading.Event()

    def terminar(_sinal: int, _quadro: object) -> None:
        parar.set()

    signal.signal(signal.SIGTERM, terminar)
    signal.signal(signal.SIGINT, terminar)
    rota.start()
    log.info(outcome="service_started")
    codigo = correr_ate(parar, recolha, lambda exc: log.excepcao(exc, "leitura_falhou"))
    http.shutdown()
    http.server_close()
    return codigo


if __name__ == "__main__":
    sys.exit(main())
