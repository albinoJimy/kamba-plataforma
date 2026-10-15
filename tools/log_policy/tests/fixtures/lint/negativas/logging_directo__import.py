"""Negativa: o `logging` da biblioteca padrao aceita texto livre."""

import logging


def tratar(pedido):
    logging.getLogger(__name__).info("pedido de %s", pedido)
