"""Nucleo partilhado pelos servicos Python da KAMBÁ (KAM-001).

Aqui so entra o que todos os servicos Python precisam de fazer da mesma maneira.
No KAM-001 isso sao duas coisas: responder a `/healthz` com a mesma carga util
que os servicos Node, e resolver anfitriao e porta com a mesma regra — para que
a sonda sintetica e o *rolling deploy* (`docs/tecnica/09` §7) nao tenham de saber em
que linguagem o servico esta escrito.
"""

from .health import COMMIT_ENV, commit_sha, healthz
from .net import DEFAULT_HOST, host, port

__all__ = [
    "COMMIT_ENV",
    "DEFAULT_HOST",
    "commit_sha",
    "healthz",
    "host",
    "port",
]
