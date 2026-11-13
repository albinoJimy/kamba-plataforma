"""O processo de lote do onboarding contra o PostgreSQL do gate — KAM-198.

O processo vive em `services/onboarding-web/src/lote/` e o adaptador SQL da fila
em `packages/core-ts/src/revisao/sql.ts`; o ensaio de base de dados e
`packages/core-ts/tests_bd/lote.bd.test.ts`. Esta suite e o que o poe a correr
contra a base descartavel, com o `kamba_batch`, o `kamba_app` e o
administrador, e as migracoes em `head`.

Porque e suite propria: e **TypeScript** contra a base, como a `tests_avisos` e
a `tests_modos`, e nenhuma das baterias de `db/tests/` corre Node. E nao e na
`tests_avisos` porque o objecto e outro — aqui e a fila de revisao da `0048`, o
`onboarding_case` da `0043` e a `screening_decision` da `0044`, e o que se prova
e o processo que os junta.

**O que esta suite nao mede**, e onde se mede: a configuracao, o arranque sem
credenciais, a recusa de um papel trocado, o aviso sem via e as rotas sao do
*gate* 4 (`services/onboarding-web/tests/lote.test.ts`); a forma do trinco e
dos onboardings sobre duplos, tambem (`packages/core-ts/tests/revisao.lote.test.ts`);
o `/metrics` sem fuga e do caso `X-01/ts/lote` do *gate* 6.
"""

from __future__ import annotations

import re
import shutil
import tempfile
import unittest
from pathlib import Path

from tests.base import ComBase
from tests_lote import node

FICHEIROS = ("tests_bd/lote.bd.test.ts",)

#: O `describe` do ficheiro. Um so: os dez cenarios partilham as sementes.
GRUPOS = ("o processo de lote contra a base",)

#: Os testes que **tem** de ter corrido e passado, pelo nome. Sao a letra dos
#: criterios do bloco: o ciclo contra a base (2), o efeito por reaplicar e o
#: screening (2), a quota entre processos (5), e a lista que sobrevive, que o
#: servico marca, que um processo nao apaga ao outro e que o lote so ve depois
#: da carencia (2), a fase que a reaplicacao nao desfaz (achado 2 da revisao
#: adversarial), e o processo inteiro a arrancar em `prod` contra a base (1 e 3).
TESTES_OBRIGATORIOS = (
    "uma volta drena a triagem, dá o alerta atrasado uma vez e mede o que a base tem",
    "o efeito por reaplicar aplica a fase, e o aviso sem via deixa-o na lista",
    "o screening de um caso de catálogo grava como kamba_app no tenant do caso, uma vez, e resolve",
    "a quota de uma origem aguenta vinte processos a abrir ao mesmo tempo; sem o trinco, não",
    "a lista de efeitos por reaplicar sobrevive a um reinício do processo",
    "o serviço marca o caso na base antes dos efeitos: uma decisão cujo aviso falha fica marcada",
    "o resolver de um processo não apaga a marca que outro escreveu depois de ele a ler",
    "a carência esconde do lote a marca de quem ainda está a correr os efeitos",
    "reaplicar um pedir_info não desfaz a fase que mudou depois da decisão; sem mudança, aplica-a",
    "o processo arranca em prod com as duas credenciais, serve /healthz e /metrics, e pára no SIGTERM",
)


class TestProcessoDeLote(ComBase):
    """Corre o ensaio em Node **uma vez**, e depois olha para o que ficou."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.saida = Path(tempfile.mkdtemp(prefix="kamba-lote-"))
        cls.execucao = node.correr(
            [
                "--test",
                "--test-concurrency=1",
                "--test-reporter=tap",
                "--test-reporter-destination=stdout",
                *FICHEIROS,
            ],
            cls.saida / "lote.tap",
        )
        cls.tap = cls.execucao.stdout
        cls.escrito = cls.execucao.stdout + cls.execucao.stderr

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.saida, ignore_errors=True)
        super().tearDownClass()

    @classmethod
    def _falhas_do_tap(cls) -> str:
        linhas = cls.escrito.splitlines()
        partes: list[str] = []
        for indice, linha in enumerate(linhas):
            if re.match(r"^\s*not ok \d+ - ", linha):
                partes.append("\n".join(linhas[indice : indice + 30]))
        resumo = [l for l in linhas if re.match(r"^# (tests|pass|fail) \d+$", l)]
        return "\n\n".join([*partes, " | ".join(resumo)]) or cls.escrito[-4000:]

    def test_o_ensaio_passa(self) -> None:
        self.assertEqual(
            self.execucao.returncode,
            0,
            f"node --test saiu com {self.execucao.returncode}:\n{self._falhas_do_tap()}",
        )

    def test_nenhum_teste_foi_saltado(self) -> None:
        """Num gate, saltar e falhar — a mesma regra do `correr_suite.py`."""
        saltados = re.findall(r"^# skip (\d+)$", self.tap, re.M)
        self.assertEqual([int(n) for n in saltados] or [0], [0], f"TAP:\n{self.tap[-3000:]}")

    def test_o_grupo_correu(self) -> None:
        for grupo in GRUPOS:
            with self.subTest(grupo=grupo):
                self.assertIn(grupo, self.tap)

    def test_os_testes_obrigatorios_passaram(self) -> None:
        """Pelo nome, e com `ok` a frente: a letra do que so a base prova."""
        for nome in TESTES_OBRIGATORIOS:
            with self.subTest(teste=nome):
                self.assertRegex(self.tap, rf"(?m)^\s*ok \d+ - {re.escape(nome)}$")

    def test_a_quota_imprime_a_medicao(self) -> None:
        """O numero do controlo sai no registo: e o que a seccao de verificacao cita."""
        medida = re.search(r"\[KAM-198\] quota (\d+): com trinco (\d+) abertos, sem trinco (\d+)", self.escrito)
        self.assertIsNotNone(medida, self.escrito[-2000:])
        print(f"    {medida.group(0)}")


if __name__ == "__main__":
    unittest.main()
