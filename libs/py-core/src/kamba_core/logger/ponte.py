"""A ponte entre o resto do processo e o *logger* (KAM-068).

Um servico nao escreve so pelo seu *logger*: as bibliotecas usam o `logging` da
biblioteca padrao, os `warnings` vao para o `stderr`, e uma excepcao que ninguem
apanha imprime o *traceback* inteiro — com a mensagem, que e onde vive o
*payload* que a fez falhar. Esta ponte apanha os quatro caminhos e deixa passar
de cada registo **so o que nao e conteudo**:

- o nivel;
- `outcome = "log_biblioteca"` (ou `"excepcao_nao_tratada"` nos ganchos);
- `error_code = <nome do logger>` e, se houver excepcao, `:<Classe>`.

Nunca `record.msg`, `record.args`, `getMessage()`, os atributos de `extra`, o
`exc_text` nem o `stack_info`. O nome do *logger* e a classe passam pela mesma
validacao de forma que qualquer `error_code`; se nao a tiverem, ficam de fora.

A ponte usa sempre o *logger* **fora** do modo estrito: o que uma biblioteca
escreve nao e um erro de quem chamou, e levantar daqui era levantar dentro do
`logging` de terceiros.
"""

from __future__ import annotations

import logging
import sys
import threading

from .politica import METRICA_ESCRITA_FALHADA, codigo_com_classe

OUTCOME_BIBLIOTECA = "log_biblioteca"
OUTCOME_NAO_TRATADA = "excepcao_nao_tratada"
CODIGO_NAO_TRATADA = "excepcao_nao_tratada"


def _nivel(numero: int) -> str:
    if numero >= logging.ERROR:
        return "error"
    if numero >= logging.WARNING:
        return "warn"
    if numero >= logging.INFO:
        return "info"
    return "debug"


class PonteLogging(logging.Handler):
    """`logging.Handler` que escreve pelo *logger* da KAMBÁ, sem conteudo."""

    def __init__(self, registo) -> None:
        super().__init__()
        self._registo = registo.tolerante()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            codigo: object = record.name
            if record.exc_info and record.exc_info[0] is not None:
                codigo = codigo_com_classe(codigo, record.exc_info[0].__name__)
            self._registo.registar(
                _nivel(record.levelno),
                (),
                {"outcome": OUTCOME_BIBLIOTECA, "error_code": codigo},
            )
        except Exception:
            # Uma excepcao que saisse daqui subia ate a biblioteca que chamou
            # `logger.info(...)`, e era ela que rebentava.
            self.handleError(record)

    def handleError(self, record: logging.LogRecord) -> None:
        # O `handleError` de origem imprime o *traceback* **e o registo** no
        # `stderr` — a mensagem que esta ponte existe para nao escrever.
        from . import CONTADORES

        CONTADORES.incrementar(METRICA_ESCRITA_FALHADA)


def ligar(registo) -> PonteLogging:
    """Liga a ponte: `logging`, `warnings` e excepcoes nao tratadas."""
    ponte = PonteLogging(registo)
    raiz = logging.getLogger()
    for existente in list(raiz.handlers):
        raiz.removeHandler(existente)
    # Um *logger* que ja tinha manipulador proprio (e `propagate=False`) escrevia
    # por ele, ao lado da ponte. Tiram-se os que existem a data; um que seja
    # configurado **depois** de `instalar` escapa, e esta dito em `docs/logs.md` §7.
    for outro in list(logging.Logger.manager.loggerDict.values()):
        if isinstance(outro, logging.Logger):
            for existente in list(outro.handlers):
                outro.removeHandler(existente)
            outro.propagate = True
    raiz.addHandler(ponte)
    raiz.setLevel(logging.INFO)
    logging.captureWarnings(True)

    tolerante = registo.tolerante()

    def nao_tratada(classe) -> None:
        nome = classe.__name__ if isinstance(classe, type) else None
        tolerante.registar(
            "error",
            (),
            {
                "outcome": OUTCOME_NAO_TRATADA,
                "error_code": codigo_com_classe(CODIGO_NAO_TRATADA, nome),
            },
        )

    def gancho(classe, _valor, _rasto) -> None:
        nao_tratada(classe)

    def gancho_de_fio(argumentos) -> None:
        # Um fio que acaba com `SystemExit` acabou de proposito; o gancho de
        # origem tambem o ignora.
        if argumentos.exc_type is SystemExit:
            return
        nao_tratada(argumentos.exc_type)

    def gancho_de_destrutor(argumentos) -> None:
        nao_tratada(argumentos.exc_type)

    sys.excepthook = gancho
    threading.excepthook = gancho_de_fio
    sys.unraisablehook = gancho_de_destrutor
    return ponte
