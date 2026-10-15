"""Negativa: `registar` e a porta sem tipos do logger; fora dele nao se usa."""

from kamba_core.logger import instalar

log = instalar("agr")


def tratar(pedido):
    log.registar("info", ("pedido recebido",), pedido)
