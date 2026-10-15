"""Positiva: nomes que contem as palavras proibidas sem o serem."""

import sys

imprimir = 1
blueprint = 2
sys_stdout = 3


class Fila:
    print_queue = ()

    def stdout(self) -> int:
        return len(self.print_queue) + len(sys.argv)
