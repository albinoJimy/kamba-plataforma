"""Passa as *fixtures* do X-11 pelo *logger* em Python.

O espelho em TypeScript e `packages/core-ts/tests/x11_conduzir.ts`. Os dois
fazem a mesma chamada por *fixture*, com o mesmo relogio parado, e escrevem
**uma linha por *fixture***: a saida dos dois compara-se byte a byte.

Este modulo e o unico de `log_policy` que importa `kamba_core.logger` — e o
que esta a ser verificado. O varrimento (`x11.py`) nao o importa.

`conduzir_ponte` exercita o que so existe em Python: o `logging` da biblioteca
padrao, os `warnings` e os ganchos de excepcoes por tratar. Repoe o estado
global do processo no fim.
"""

from __future__ import annotations

import datetime
import io
import logging
import sys
import threading
import warnings

from kamba_core import logger as kamba_logger

RELOGIO_PARADO = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
SERVICO = "x11"


def _relogio() -> datetime.datetime:
    return RELOGIO_PARADO


def conduzir(fixtures: list[dict]) -> tuple[str, dict[str, int]]:
    """As linhas escritas para as *fixtures* dadas, e os contadores no fim."""
    saida = io.StringIO()
    registo = kamba_logger.Logger(SERVICO, destino=saida, relogio=_relogio, estrito=False)
    kamba_logger.CONTADORES.repor()
    for fixture in fixtures:
        chamada = fixture["chamada"]
        if chamada["erro"] is not None:
            classe = type(chamada["erro"]["classe"], (Exception,), {})
            registo.excepcao(
                classe(chamada["erro"]["mensagem"]), chamada["codigo"], **chamada["campos"]
            )
        else:
            registo.registar(chamada["nivel"], chamada["posicionais"], chamada["campos"])
    contadores = kamba_logger.CONTADORES.ler()
    kamba_logger.CONTADORES.repor()
    return saida.getvalue(), contadores


def conduzir_ponte(fixtures: list[dict]) -> str:
    """Os canarios pelo `logging`, pelos `warnings` e pelos ganchos."""
    saida = io.StringIO()
    raiz = logging.getLogger()
    antes = (
        list(raiz.handlers),
        raiz.level,
        sys.excepthook,
        threading.excepthook,
        sys.unraisablehook,
        warnings.showwarning,
    )
    try:
        kamba_logger.instalar(SERVICO, destino=saida, relogio=_relogio, estrito=False)
        biblioteca = logging.getLogger("biblioteca.de_terceiros")
        for fixture in fixtures:
            for canario in fixture["canarios"]:
                _pela_ponte(biblioteca, canario)
    finally:
        logging.captureWarnings(False)
        for manipulador in list(raiz.handlers):
            raiz.removeHandler(manipulador)
        for manipulador in antes[0]:
            raiz.addHandler(manipulador)
        raiz.setLevel(antes[1])
        sys.excepthook, threading.excepthook, sys.unraisablehook = antes[2:5]
        warnings.showwarning = antes[5]
        kamba_logger.CONTADORES.repor()
    return saida.getvalue()


def _pela_ponte(biblioteca: logging.Logger, canario: str) -> None:
    # A mensagem, os argumentos, o `extra`, a pilha e a excepcao: os cinco
    # sitios de um registo onde uma biblioteca poe o que estava a tratar.
    biblioteca.warning("pedido de %s falhou", canario)
    biblioteca.error(canario)
    biblioteca.info(
        "com contexto",
        extra={"telefone": canario, "contexto": {"headers": {"Authorization": canario}}},
    )
    biblioteca.warning("com pilha: %s", canario, stack_info=True)
    try:
        raise ValueError(f"nao foi possivel tratar {canario}")
    except ValueError:
        biblioteca.exception("falhou com %s", canario)
        tipo, valor, rasto = sys.exc_info()
        sys.excepthook(tipo, valor, rasto)
    # Um registo mal formado: o `logging` chama `handleError`, que de origem
    # imprime o registo no `stderr`.
    biblioteca.error("sem argumento para %s e %s", canario)
    # Um *logger* cujo nome e o proprio canario.
    logging.getLogger(canario).error("nome de logger com conteudo")
    with warnings.catch_warnings():
        warnings.simplefilter("always")
        warnings.warn(f"aviso sobre {canario}", UserWarning, stacklevel=1)

    def rebenta() -> None:
        raise RuntimeError(f"num fio, com {canario}")

    fio = threading.Thread(target=rebenta)
    fio.start()
    fio.join()
