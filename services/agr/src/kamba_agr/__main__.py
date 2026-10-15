"""Arranque do AGR.

Escuta em `127.0.0.1` por omissao. Dentro de um contentor e preciso escutar em
`0.0.0.0` para que a rede do compose chegue ao processo, e e por isso que o
`Dockerfile` define `HOST=0.0.0.0` — mas nunca o faz o codigo por si, para que
correr o servico a mao na maquina de alguem nao abra uma porta na rede local
(`specs/01` §6, principio 7, e o DoD do KAM-001).

E o espelho de `services/*/src/server.ts` do lado Python: a regra tem de ser a
mesma nas duas linguagens, ou o `.env` passa a significar coisas diferentes em
servicos diferentes.

Tudo o que este processo escreve sai pelo `kamba_core.logger` (KAM-068,
`docs/logs.md`): `instalar` liga tambem o `logging` da biblioteca padrao — que
e por onde o uvicorn escreve — e as excepcoes por tratar. O uvicorn arranca com
`log_config=None` para **nao** instalar os seus proprios manipuladores, que
escreveriam texto livre ao lado das linhas JSON.
"""

from __future__ import annotations

import uvicorn
from kamba_core import host, port
from kamba_core.logger import instalar

from .meta import DEFAULT_PORT, SERVICE


def main() -> int:
    log = instalar(SERVICE)
    try:
        listen_host, listen_port = host(), port(DEFAULT_PORT)
    except ValueError as exc:
        # So o codigo e a classe. A mensagem de `port()` repete o valor de
        # `PORT`, e um valor de ambiente errado pode ser qualquer coisa.
        log.excepcao(exc, "arranque_invalido")
        return 2

    # O anfitriao e a porta nao estao na *allowlist* de `docs/tecnica/08` §7.3.
    log.info(outcome="service_started")
    uvicorn.run(
        "kamba_agr.app:app",
        host=listen_host,
        port=listen_port,
        log_level="info",
        log_config=None,
        access_log=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
