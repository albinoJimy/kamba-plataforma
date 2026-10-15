"""Positiva: falar de print() e de logging numa docstring nao e usa-los.

    print("isto e documentacao")
    import logging
"""

from kamba_core.logger import instalar

log = instalar("agr")


def tratar() -> None:
    # print("isto e um comentario")
    log.info(outcome="ok")
