"""O aviso ao dono (TypeScript) contra o PostgreSQL do gate — KAM-115.

O codigo vive em `packages/core-ts/src/avisos/` e os seus testes de base de
dados em `packages/core-ts/tests_bd/avisos.bd.test.ts`. Esta suite e o que os poe
a correr contra a base descartavel, com os **tres** papeis que o ensaio precisa
— `kamba_app` (duas ligacoes), `kamba_batch` e o administrador — e as migracoes
em `head`, e e ela que le o que eles deixam: a saida, os grupos que correram e a
cobertura de `src/avisos/`.

Porque e suite propria, e nao mais um ficheiro em `tests` nem na `tests_modos`:
e **TypeScript** contra a base, como as de identidade, eventos, CHR, saida,
handoff, midia e modos, e nenhuma das baterias de `db/tests/` corre Node. E nao
e na `tests_modos` porque a cobertura ali e medida sobre `src/modos/` — o filtro
do `_cobertura` e literal — e o modulo deste ticket e outro.

**O que esta suite nao mede**, e onde se mede: as regras — os cinco gatilhos, os
dois limites de frequencia, os lembretes, a lista branca de modelos, o
varrimento de 200 avisos e a configuracao sem WhatsApp — vivem na bateria do
*gate* 4, em `packages/core-ts/tests/avisos.test.ts`. Sao funcoes puras e ordem
de chamadas, e uma base real nao acrescenta nada a prova. Os `CHECK`, os
dominios e os privilegios por nome vivem em `db/tests/test_avisos_schema.py`, que
corre no `--suite tests`.

**E o que nao se mede em sitio nenhum, por nao existir:** o fornecedor de e-mail
verdadeiro, e o criterio 3 manda-o explicitamente — «medida com relogio
acelerado e fornecedor falso». A escolha do fornecedor e um subprocessador com
procedimento APD (KAM-069, ADR-008) e o `apd_ref` esta `pendente`, pelo que o
gate de transferencia bloqueia `prod` por desenho e nao por esquecimento.
"""

from __future__ import annotations

import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from tests.base import ComBase
from tests_avisos import node

sys.path.insert(0, str(node.RAIZ / "tools"))

from kamba_yaml import load_file  # noqa: E402

#: Os ficheiros de teste, pela ordem em que correm. O de cima nao precisa de
#: base (corre tambem no gate 4) e esta aqui pela cobertura: sem ele, a medida
#: de `src/avisos/` nao incluiria o que ele exercita — os cinco gatilhos, os
#: dois limites, os lembretes e a lista branca de modelos — e o limiar nao se
#: podia aplicar por ficheiro.
FICHEIROS = (
    "tests/avisos.test.ts",
    "tests_bd/avisos.bd.test.ts",
)

#: O grupo de `tests_bd/avisos.bd.test.ts`. Um so, e e de proposito: o ficheiro
#: tem um `describe` e a razao esta na docstring dele — o que **so** contra a
#: base se prova nao se divide por criterio, divide-se por propriedade do
#: servidor, e as seis propriedades partilham o mesmo cenario de dois tenants e
#: tres ligacoes.
GRUPOS = ("o aviso ao dono contra a base",)

#: Testes que **tem** de ter corrido e passado, pelo nome. Lista curta, com os
#: que dao a letra do que so a base pode provar. Se um desaparecer, a suite
#: deixa de provar essa propriedade — e isso tem de falhar aqui, nao passar por
#: haver menos testes.
TESTES_OBRIGATORIOS = (
    "as consultas do módulo correm contra o servidor",
    "**o endereço nunca é escrito em claro em nenhuma coluna**",
    "duas transacções concorrentes com a mesma chave deixam **uma** linha",
    "o lembrete das 24 h entra ao lado do aviso, na mesma chave",
    "**o quarto lembrete é recusado pelo servidor, e não por um `if`**",
    "duas confirmações simultâneas do mesmo *token* dão **uma**",
    "a varredura dos lembretes corre com `BYPASSRLS` e vê os dois tenants",
    "**a mesma varredura com `kamba_app` não vê nada**",
    "**o denominador da métrica conta os `ativo` e não todos**",
    "com o contexto de A, o aviso de B não se lê",
    "com o contexto de A, o aviso de B não se muda",
    "com o contexto de A, o contacto de B não se lê nem se invalida",
    "`kamba_app` escreve o desfecho e **não** a chave do aviso",
    "o *bounce* invalida o contacto pelo caminho do módulo",
    "**um contacto inválido faz o aviso seguinte falhar com `sem_contacto`**",
    "**um episódio com os dois lembretes aparece como esgotado**",
    "**uma ligação expirada não confirma, e o prazo está na instrução**",
    "**a varredura só conta o contacto verificado e não inválido**",
)

#: Os testes do gate 4 que dao a letra dos criterios de regra. Correm aqui
#: tambem (pela cobertura), e conferem-se aqui pelo nome porque a seccao de
#: verificacao do ticket os cita.
TESTES_DAS_REGRAS = (
    "um gatilho fora da lista não envia nada",
    "o mesmo evento 3× produz 1 aviso por canal",
    "500 eventos numa hora de um só tenant enviam ≤ 3 avisos",
    "**um lembrete não é recusado pela janela do gatilho**",
    "**o varrimento de 200 avisos não encontra nada do que o critério proíbe**",
    "**nenhum `import` do módulo vem do `outbound` nem do `entrada`**",
    "**em `prod`, sem `apd_ref`, o serviço não arranca**",
    "**a linha de `sem_contacto` entra nos avisos devolvidos**",
    "**a hora sai em `Africa/Luanda` e na forma longa**",
    "**a janela do gatilho não morde um lembrete, e a prova precisa de um vizinho**",
    "**a linha deduplicada por outra transacção não se entrega**",
    "**nenhum modelo leva um marcador que a lista fechada não tenha**",
)

#: Os ficheiros do modulo. A cobertura mede-se em **cada um**.
FICHEIROS_DO_MODULO = (
    "avisos.ts",
    "consultas.ts",
    "contrato.ts",
    "decisao.ts",
    "fornecedor.ts",
    "metricas.ts",
    "modelos.ts",
    "index.ts",
)


def _cobertura(lcov: str) -> dict[str, tuple[int, int]]:
    """ficheiro de `src/avisos/` -> (linhas cobertas, linhas encontradas)."""
    medidas: dict[str, tuple[int, int]] = {}
    actual = None
    cobertas = encontradas = 0
    for linha in lcov.splitlines():
        if linha.startswith("SF:"):
            actual = linha[3:].replace("\\", "/")
            cobertas = encontradas = 0
        elif linha.startswith("DA:") and actual is not None:
            _, execucoes = linha[3:].split(",")[:2]
            encontradas += 1
            cobertas += int(execucoes) > 0
        elif linha == "end_of_record" and actual is not None:
            if "/src/avisos/" in f"/{actual}":
                medidas[actual.rsplit("/", 1)[-1]] = (cobertas, encontradas)
            actual = None
    return medidas


class TestModuloDoAviso(ComBase):
    """Corre os testes em Node **uma vez**, e depois olha para o que ficou."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.saida = Path(tempfile.mkdtemp(prefix="kamba-avisos-"))
        cls.execucao = node.correr(
            [
                "--test",
                # Um ficheiro de cada vez: o ensaio de base abre tres ligacoes e
                # disputa a mesma chave de unicidade em duas delas; dois
                # ficheiros em paralelo disputavam-na entre si e o teste que
                # mede «uma das duas escreveu» passava a medir a carga da
                # maquina.
                "--test-concurrency=1",
                "--experimental-test-coverage",
                "--test-reporter=tap",
                "--test-reporter-destination=stdout",
                "--test-reporter=lcov",
                "--test-reporter-destination={saida}",
                *FICHEIROS,
            ],
            cls.saida / "avisos.lcov",
        )
        cls.tap = cls.execucao.stdout
        cls.escrito = cls.execucao.stdout + cls.execucao.stderr

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.saida, ignore_errors=True)
        super().tearDownClass()

    @classmethod
    def _falhas_do_tap(cls) -> str:
        """As linhas `not ok` e o que vem com cada uma, so.

        O relatorio de cobertura ocupa milhares de linhas no fim da saida, e um
        `escrito[-6000:]` na mensagem de falha mostrava **so** isso. E a mesma
        funcao da `tests_modos`, pela mesma razao medida.
        """
        linhas = cls.escrito.splitlines()
        partes: list[str] = []
        for indice, linha in enumerate(linhas):
            if re.match(r"^\s*not ok \d+ - ", linha):
                partes.append("\n".join(linhas[indice : indice + 30]))
        resumo = [l for l in linhas if re.match(r"^# (tests|pass|fail) \d+$", l)]
        return "\n\n".join([*partes, " | ".join(resumo)]) or cls.escrito[-4000:]

    def test_os_testes_do_aviso_passam(self) -> None:
        """As falhas do TAP entram na mensagem: e o que se vai ler."""
        self.assertEqual(
            self.execucao.returncode,
            0,
            f"node --test saiu com {self.execucao.returncode}:\n"
            f"{self._falhas_do_tap()}",
        )

    def test_nenhum_teste_foi_saltado(self) -> None:
        """Num gate, saltar e falhar — a mesma regra do `correr_suite.py`."""
        saltados = re.findall(r"^# skip (\d+)$", self.tap, re.M)
        self.assertEqual(
            [int(n) for n in saltados] or [0], [0], f"TAP:\n{self.tap[-3000:]}"
        )

    def test_o_grupo_de_base_de_dados_correu(self) -> None:
        """Um grupo que desapareca e uma propriedade que deixou de se provar."""
        for grupo in GRUPOS:
            with self.subTest(grupo=grupo):
                self.assertIn(grupo, self.tap)

    def test_os_testes_obrigatorios_passaram(self) -> None:
        """Pelo nome, e com `ok` a frente: a letra do que so a base prova."""
        for nome in TESTES_OBRIGATORIOS:
            with self.subTest(teste=nome):
                self.assertRegex(self.tap, rf"(?m)^\s*ok \d+ - {re.escape(nome)}$")

    def test_os_testes_das_regras_passaram(self) -> None:
        """Os do gate 4 que a seccao de verificacao do ticket cita."""
        for nome in TESTES_DAS_REGRAS:
            with self.subTest(teste=nome):
                self.assertRegex(self.tap, rf"(?m)^\s*ok \d+ - {re.escape(nome)}$")

    def test_os_cinco_gatilhos_foram_todos_afirmados(self) -> None:
        """O criterio 1 pede os **cinco**, e nao uma amostra.

        Conta-se o grupo que os enumera em vez de os listar aqui um a um: uma
        lista de cinco nomes em `TESTES_OBRIGATORIOS` era repetir o que o
        ficheiro TypeScript ja enumera, e e isso que o KAM-018 escreveu para as
        32 celulas dele.
        """
        self.assertRegex(
            self.tap,
            r"(?m)^\s*ok \d+ - há cinco gatilhos e cinco modelos, um por gatilho$",
        )
        self.assertRegex(
            self.tap,
            r"(?m)^\s*ok \d+ - os cinco gatilhos geram aviso, cada um com o seu "
            r"texto e o seu passo$",
        )

    def test_a_cobertura_do_modulo_e_pelo_menos_a_do_estrato_critico(self) -> None:
        """O gate 4 nao tem base de dados; a cobertura de `src/avisos/` mede-se aqui.

        O limiar e **lido** de `ci/thresholds.yaml`, do estrato `critico`, e nao
        escrito aqui: dois numeros em dois sitios divergem. O aviso ao dono entra
        nesse estrato por duas razoes deste ticket: e o unico modulo que le e
        escreve um **dado pessoal de uma pessoa singular** — o e-mail do dono —,
        e um defeito aqui e um dono que nao sabe que a loja dele parou de
        atender.
        """
        lcov = self.saida / "avisos.lcov"
        self.assertTrue(lcov.is_file(), f"nao houve LCOV:\n{self.escrito[-3000:]}")
        medidas = _cobertura(lcov.read_text(encoding="utf-8"))
        limiares = load_file(node.RAIZ / "ci" / "thresholds.yaml")
        minimo = next(
            int(e["minimo_linhas"])
            for e in limiares["estratos"]
            if e["nome"] == "critico"
        )
        em_falta = [f for f in FICHEIROS_DO_MODULO if f not in medidas]
        self.assertEqual(
            em_falta, [], f"sem medida: {em_falta}; medidos: {sorted(medidas)}"
        )
        for ficheiro in FICHEIROS_DO_MODULO:
            cobertas, encontradas = medidas[ficheiro]
            percentagem = 100 * cobertas / max(encontradas, 1)
            # **Imprime-se, e nao e ruido.** E a licao que a `tests_chr` escreveu
            # para a latencia do `resolve` e a `tests_modos` repetiu: um numero
            # que so aparece quando o teste falha e um numero que a seccao de
            # verificacao do ticket nao pode citar.
            print(
                f"    [KAM-115] cobertura src/avisos/{ficheiro}: "
                f"{cobertas}/{encontradas} = {percentagem:.0f}% (minimo {minimo}%)"
            )
            with self.subTest(ficheiro=ficheiro):
                self.assertGreaterEqual(
                    percentagem,
                    minimo,
                    f"{ficheiro}: {cobertas}/{encontradas} = {percentagem:.0f}%",
                )


if __name__ == "__main__":
    unittest.main()
