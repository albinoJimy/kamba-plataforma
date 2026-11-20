"""`python -m kamba_core.offboarding` — o processo das fases de dados (KAM-218).

So ligacoes: le o ambiente, abre o cofre, constroi as portas e arranca a sonda e
o ciclo. A decisao esta em `servico.py` e `processo.py`, que se testam sem rede
nem base; este ficheiro fica fora da medicao do *gate* 4 como os outros
`__main__.py` (`ci/thresholds.yaml`).

Corre com a imagem do AGR (`services/agr/Dockerfile`), que traz o `pg8000` e o
`kamba_core`, num servico de *compose* proprio — `offboarding-dados` —, como o
`idx`.

Codigos de saida: 2 cofre ou configuracao, 0 paragem pedida.
"""

from __future__ import annotations

import os
import signal
import sys
import threading
from typing import Any

from kamba_core.logger import instalar
from kamba_core.secrets import EnvSecretProvider, Secrets
from kamba_core.storage import criar_storage_s3

from .servico import (
    SEGREDOS_OBRIGATORIOS,
    SERVICO,
    Ciclo,
    desfecho,
    ler_configuracao,
    ligadores,
    portas_de_producao,
    servidor,
)


def main(ambiente: Any = None) -> int:
    ambiente = os.environ if ambiente is None else ambiente
    log = instalar(SERVICO)
    try:
        config = ler_configuracao(ambiente)
        segredos = Secrets.arrancar(
            servico=SERVICO,
            provider=EnvSecretProvider(config.ambiente, ambiente),
            obrigatorios=list(SEGREDOS_OBRIGATORIOS),
        )
        armazenamento = criar_storage_s3(config=config.armazenamento, secrets=segredos)
        portas = portas_de_producao(config, segredos, armazenamento, ambiente)
    except Exception as exc:  # noqa: BLE001 — qualquer falha de arranque aborta
        log.excepcao(exc, "arranque_invalido")
        return 2

    abrir_batch, abrir_app = ligadores(ambiente)
    ciclo = Ciclo(abrir_batch, abrir_app, portas)
    # A entrega do certificado nao tem adaptador (KAM-116 e KAM-115 por escolher):
    # sem esta linha o silencio lia-se como entrega ligada.
    log.info(outcome="offboarding_entrega", error_code="entrega_sem_adaptador")

    def ao_terminar(r: Any) -> None:
        outcome, codigo = desfecho(r)
        if codigo is None:
            log.info(outcome=outcome)
        else:
            log.error(outcome=outcome, error_code=codigo)

    http = servidor(config.porta, ambiente, anfitriao=ambiente.get("HOST", "127.0.0.1"))
    parar = threading.Event()
    fio = threading.Thread(
        target=ciclo.correr,
        args=(parar, config.intervalo_s, ao_terminar, lambda exc: log.excepcao(exc, "volta_falhou")),
        name="offboarding-dados-ciclo",
        daemon=True,
    )

    def terminar(_sinal: int, _quadro: object) -> None:
        parar.set()
        threading.Thread(target=http.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, terminar)
    signal.signal(signal.SIGINT, terminar)
    fio.start()
    log.info(outcome="service_started")
    http.serve_forever()
    http.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
