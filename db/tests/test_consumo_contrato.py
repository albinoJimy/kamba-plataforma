"""Os acoplamentos do consumidor que nenhum teste de execucao ve (KAM-006).

Ha propriedades que vivem **entre** dois ficheiros e que uma suite de execucao
nao distingue de uma coincidencia. A que paga esta classe de teste:

> O BullMQ so chama o `backoffStrategy` do *worker* se as opcoes do *job*
> disserem `backoff: {type: 'custom'}` — e quem cria o *job* e o **publicador**.
> Com o `exponential` que lá estava, a escada do §6.4 (1 s, 5 s, 30 s, 2 min,
> 10 min) nunca era consultada e o recuo real era 1 s, 2 s, 4 s, 8 s, 16 s: a
> contagem de tentativas do criterio 2 ficava certa e os **intervalos**
> errados. Uma suite de integracao com relogio acelerado nao apanha isto, e uma
> com a escada real custava 756 s por teste.

O padrao e o do `TestParidadeDoGuardaDePii` do KAM-005: le-se o TypeScript
**como texto** e confronta-se. Nao substitui os testes de execucao — diz o que
eles nao podem dizer.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
EVENTOS = RAIZ / "packages" / "core-ts" / "src" / "eventos"
FILAS = EVENTOS / "filas_bullmq.ts"
TRABALHADOR = EVENTOS / "trabalhador_bullmq.ts"
CONSUMO = EVENTOS / "consumo.ts"


class TestOsFicheirosExistem(unittest.TestCase):
    def test_os_tres_ficheiros_estao_la(self) -> None:
        for ficheiro in (FILAS, TRABALHADOR, CONSUMO):
            with self.subTest(ficheiro=ficheiro.name):
                self.assertTrue(ficheiro.is_file(), ficheiro)


class TestEscadaDoConsumidor(unittest.TestCase):
    """O *job* pede a escada e o *worker* da-a. As duas metades, juntas."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.filas = FILAS.read_text(encoding="utf-8")
        cls.trabalhador = TRABALHADOR.read_text(encoding="utf-8")
        cls.consumo = CONSUMO.read_text(encoding="utf-8")

    def test_o_job_pede_a_escada_do_consumidor(self) -> None:
        """`backoff: { type: "custom" }` nas opcoes do `addBulk`."""
        self.assertIn('backoff: { type: "custom" },', self.filas)
        self.assertNotIn('type: "exponential"', self.filas)

    def test_o_trabalhador_da_a_escada_que_o_job_pede(self) -> None:
        self.assertIn("backoffStrategy:", self.trabalhador)
        self.assertIn("atrasoDaTentativaDoConsumidor(", self.trabalhador)

    def test_um_adiar_traz_o_seu_atraso_e_nao_o_degrau(self) -> None:
        """Os 5 s do §6.3 nao se confundem com o degrau da escada.

        Sao duas razoes diferentes para esperar: o `Adiar` e «a pre-condicao
        ainda nao chegou» (5 s, e tenta-se outra vez depressa); o degrau e «isto
        falhou» (e cresce). Um `Adiar` a herdar o degrau esperava dez minutos
        por uma encomenda que ia ser paga a seguir.
        """
        self.assertIn("erro instanceof Adiar", self.trabalhador)
        self.assertIn("erro.atrasoMs", self.trabalhador)

    def test_o_numero_de_tentativas_do_job_e_o_da_escada(self) -> None:
        """`REPETICAO.tentativas` e `1 + ESCADA_DO_CONSUMIDOR.length` sao 6.

        Dois numeros em dois ficheiros, e o criterio 2 so esta satisfeito se
        forem o mesmo: com `attempts` a 3, a DLQ abria a terceira tentativa; com
        `attempts` a 10, abria a sexta e o *job* continuava a ser retentado.
        """
        filas_ts = (EVENTOS / "filas.ts").read_text(encoding="utf-8")
        achado = re.search(r"REPETICAO: Repeticao = \{ tentativas: (\d+),", filas_ts)
        self.assertIsNotNone(achado, "nao se encontrou REPETICAO em filas.ts")
        escada = re.search(
            r"ESCADA_DO_CONSUMIDOR = \[(.*?)\] as const;", self.consumo, re.S
        )
        self.assertIsNotNone(escada, "nao se encontrou a escada em consumo.ts")
        degraus = len(re.findall(r"[0-9_]+", escada.group(1)))
        self.assertEqual(int(achado.group(1)), 1 + degraus)
        self.assertEqual(int(achado.group(1)), 6, "o criterio 2 diz 6 (1 + 5)")


class TestUmaLigacaoPorFila(unittest.TestCase):
    """A ligacao e por fila, e isso nao se ve a correr com uma particao."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.trabalhador = TRABALHADOR.read_text(encoding="utf-8")

    def test_a_opcao_e_uma_fabrica_e_nao_uma_ligacao(self) -> None:
        """`concurrency: 1` limita a fila, nao o processo.

        Dezesseis filas sao dezesseis trabalhos ao mesmo tempo. Com uma ligacao
        partilhada, os `BEGIN` e `COMMIT` de dezesseis transaccoes
        intercalavam-se na mesma sessao — um `COMMIT` de uma fila fechava a
        transaccao de outra, e a marca de consumo de um evento ficava confirmada
        com o efeito de outro. Uma suite que corra um evento de cada vez nunca
        ve isto.
        """
        self.assertIn("readonly ligar: () => Promise<LigacaoDoTrabalhador>", self.trabalhador)
        self.assertNotIn("readonly bd: ClienteSql;", self.trabalhador)

    def test_a_concorrencia_por_fila_e_um(self) -> None:
        self.assertIn("concurrency: 1,", self.trabalhador)


if __name__ == "__main__":
    unittest.main()
