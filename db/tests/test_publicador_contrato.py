"""O que o publicador promete e nenhuma execucao da suite alcanca (KAM-005).

O padrao e o do `db/tests/test_consumo_contrato.py`: le-se o TypeScript **como
texto** e confronta-se. Nao substitui os testes de execucao de
`db/tests_eventos/` — diz o que eles **nao podem** dizer.

**A propriedade que paga este ficheiro.** Os *advisory locks* de sessao do
PostgreSQL sao contados por referencia: um `pg_try_advisory_lock` na sessao que
ja o detem devolve `true` e **incrementa** a contagem. Por isso o `catch` do
laco de `correr()` tem de **largar** o *lock*, e nao apenas limpar a marca de
lider: com `#lider = false`, um erro transitorio fazia a volta seguinte
re-eleger e a contagem subir a 2, e no encerramento limpo o `largar()` descia a
1 — a sessao continuava a deter o *lock*, a replica deixava de assumir em ≤ 10 s
(criterio 5) e passava a esperar a deteccao de ligacao morta, que e escala de
minutos.

**Porque e por texto, e nao em `tests_eventos`.** Nenhum teste da suite com fila
provoca um erro transitorio no lider **sem o matar**:

* o `parar()` aborta o sinal e sai pelo `await this.largar()` de **fora** do
  laco, que nao e esta linha;
* as falhas tipicas nao chegam a este `catch` — o `#recuar` tem `catch` proprio
  que engole a falha da base, e o `#reverter()` corre antes;
* o `matar()` (`kill -9`) do `TestLideranca` fecha a ligacao, e o servidor larga
  o *lock* de sessao sozinho, o que torna a contagem irrelevante.

Medir isto por execucao exigiria um gancho novo no `publicador_runner.ts` para
fazer um ciclo falhar sem morrer. Fica como trabalho de quem precisar dele; o
contrato prende-se aqui, onde se consegue afirmar hoje — e a mutacao
`eventos: um erro transitorio deixa o lock preso` passa a correr na suite
`tests`, que e esta.
"""

from __future__ import annotations

import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
PUBLICADOR = RAIZ / "packages" / "core-ts" / "src" / "eventos" / "publicador.ts"

#: O inicio e o fim do `catch` do laco de `correr()`. O fim e o `await esperar`,
#: que e a primeira instrucao depois do bloco — e nao um `}`, que apareceria
#: dentro dele.
ABRE_O_CATCH = "} catch (erro) {"
FECHA_O_CATCH = "await esperar(this.#intervalo, sinal);"


class TestOCatchDoLacoLargaOLock(unittest.TestCase):
    """Criterio 5: o erro transitorio nao pode deixar o *lock* preso."""

    @classmethod
    def setUpClass(cls) -> None:
        corpo = PUBLICADOR.read_text(encoding="utf-8")
        inicio = corpo.index(ABRE_O_CATCH)
        fim = corpo.index(FECHA_O_CATCH, inicio)
        cls.bloco = corpo[inicio:fim]

    def test_o_bloco_de_erro_existe_e_e_o_do_laco(self) -> None:
        """O canario: sem isto, um `catch` que desaparecesse dava bloco vazio.

        Um bloco vazio passa qualquer `assertNotIn`, e o `assertIn` de baixo
        falharia pela razao errada — «o texto nao esta la» em vez de «o lock
        nao se larga». Afirma-se primeiro que se esta a olhar para o sitio certo.
        """
        self.assertIn('this.#log?.excepcao(erro, "evt_ciclo_falhou");', self.bloco)

    def test_o_erro_transitorio_larga_o_lock(self) -> None:
        self.assertIn("await this.largar();", self.bloco)

    def test_o_erro_transitorio_nao_se_contenta_com_a_marca_de_lider(self) -> None:
        """A correccao errada, nomeada: limpar a marca sem largar o *lock*."""
        self.assertNotIn("this.#lider = false", self.bloco)
