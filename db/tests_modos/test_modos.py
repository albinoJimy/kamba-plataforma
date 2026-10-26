"""Os modos da conversa (TypeScript) contra o PostgreSQL do gate — KAM-018.

O codigo vive em `packages/core-ts/src/modos/` e os seus testes de base de dados
em `packages/core-ts/tests_bd/modos.bd.test.ts`. Esta suite e o que os poe a
correr contra a base descartavel, com os **tres** papeis que o ensaio precisa —
`kamba_app` (tres ligacoes), `kamba_resolver` e o administrador — e as migracoes
em `head`, e e ela que le o que eles deixam: a saida, os numeros que eles medem e
a cobertura de `src/modos/`.

Porque e suite propria, e nao mais um ficheiro em `tests` nem na `tests_chr`: e
**TypeScript** contra a base, como as de identidade, eventos, CHR, saida,
handoff e midia, e nenhuma das baterias de `db/tests/` corre Node. E nao e na
`tests_chr` porque a cobertura ali e medida sobre `src/chr/` — o filtro do
`_cobertura` e literal — e o modulo deste ticket e outro.

**O que esta suite nao mede**, e onde se mede: a tabela de transicoes celula a
celula (as 32), a condicao do silencio do dono, a ordem das instrucoes e o
mapeamento dos quatro modos para os tres valores do contrato publicado vivem nas
baterias do gate 4, em `packages/core-ts/tests/modos.transicoes.test.ts` e
`modos.test.ts` — sao funcoes puras e ordem de chamadas, e uma base real nao
acrescenta nada a prova. O que **so** aqui se prova esta na docstring do ficheiro
TypeScript.

**E o que nao se mede em sitio nenhum, por nao existir:** a transicao
`bot->dono` por *echo* real (precisa de `smb_message_echoes`, KAM-017) e a
metrica `echo_latency_ms` (pede >= 30 *echoes* de *staging* com numeros +244,
R6/L6, KAM-100). Nesta bateria o gatilho `echo_do_dono` e **disparado** pelo
ensaio, que e o que a maquina expoe.
"""

from __future__ import annotations

import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from tests.base import ComBase
from tests_modos import node

sys.path.insert(0, str(node.RAIZ / "tools"))

from kamba_yaml import load_file  # noqa: E402

#: Os ficheiros de teste, pela ordem em que correm. Os de cima nao precisam de
#: base (correm tambem no gate 4) e estao aqui pela cobertura: sem eles, a
#: medida de `src/modos/` nao incluiria o que eles exercitam — a tabela de
#: transicoes inteira, a exposicao das metricas e o mapeamento do evento — e o limiar do estrato
#: `critico` nao se podia aplicar por ficheiro.
FICHEIROS = (
    "tests/modos.transicoes.test.ts",
    "tests/modos.metricas.test.ts",
    "tests/modos.test.ts",
    "tests_bd/modos.bd.test.ts",
)

#: Os grupos de `tests_bd/modos.bd.test.ts`: um por propriedade que **so** se
#: prova contra a base. Se um desaparecer, a suite deixa de provar essa
#: propriedade — e isso tem de falhar aqui, nao passar por haver menos testes.
GRUPOS = (
    "critério 2 — o lock da conversa serializa a transição e a guarda",
    "critério 3 — a corrida echo vs resposta do bot",
    "critério 4 — o silenciamento é por conversa e não por canal",
    "critério 5 — 0 invocações do AGR fora do modo `bot`",
    "critério 7 — o opt-out e o job das 24 h",
    "critério 6 — o evento vai para o outbox, na mesma transacção",
    "DoD — o privilégio da revisão 0016, por coluna",
    "DoD — isolamento de tenant (X-03)",
)

#: Testes que **tem** de ter corrido e passado, pelo nome. Lista curta, com os
#: que dao a letra de cada criterio — e com os dois que fecham as caixas que o
#: KAM-015 e o KAM-019 tiveram de deixar vazias.
TESTES_OBRIGATORIOS = (
    "a guarda bloqueia a porta de uma transicao em curso, e entra com o modo novo",
    "duas transicoes concorrentes deixam uma transicao e um evento",
    "turno em t0, echo em t0+1s, resposta em t0+2s: 0 enviadas e 1 suprimida",
    "as 100 intercalacoes: 0 mensagens depois de o echo estar registado",
    "as 100 intercalacoes sao reproduziveis: a mesma semente da a mesma sequencia",
    "duas conversas do mesmo canal, A em `dono` e B em `bot`, respondem independentemente",
    "nos tres modos que nao sao `bot`, o CHR entrega ao dono e 0 jobs vao ao AGR",
    "sem actividade humana, conta do `handoffs.opened_at` mais recente",
    "correr o job duas vezes seguidas pausa N e depois 0",
    "se a emissao levantar, a transicao e desfeita",
    "`kamba_app` consegue agora escrever `mode` e `last_human_activity_at`",
    "`kamba_app` continua sem poder reescrever a identidade da conversa",
    "com o contexto de A, o modo de B nao se le nem se muda",
    # As duas que nasceram **da** prova por mutacao e nao estavam presas pelo
    # nome. O KAM-018 converteu tres mutacoes sobreviventes em testes; a
    # terceira ficou na lista e estas duas nao, e so o `returncode == 0` do
    # `test_os_testes_dos_modos_passam` as defendia. Quem as renomeie, marque
    # `skip` ou apague nao faz falhar afirmacao nenhuma do lado Python, e a
    # mutacao volta a sobreviver sem ninguem dar por isso.
    #
    # A primeira e a unica que mata o `FOR UPDATE` da transicao: tem de correr
    # o `SQL_MUDAR_MODO` **sem** o `pg_advisory_xact_lock`, porque com ele as
    # duas sessoes serializam-se e a diferenca desaparece — defesa em
    # profundidade genuina, e por isso a prova tem de a contornar.
    "o UPDATE ganha a corrida **sem** o lock: a atomicidade e da linha",
    "um echo fora de ordem nao faz a actividade humana andar para tras",
)

#: Os ficheiros do modulo. A cobertura mede-se em **cada um**.
FICHEIROS_DO_MODULO = (
    "consultas.ts",
    "contrato.ts",
    "eventos.ts",
    "guarda.ts",
    "metricas.ts",
    "modos.ts",
    "transicoes.ts",
    "index.ts",
)


def _cobertura(lcov: str) -> dict[str, tuple[int, int]]:
    """ficheiro de `src/modos/` -> (linhas cobertas, linhas encontradas)."""
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
            if "/src/modos/" in f"/{actual}":
                medidas[actual.rsplit("/", 1)[-1]] = (cobertas, encontradas)
            actual = None
    return medidas


class TestModuloDosModos(ComBase):
    """Corre os testes em Node **uma vez**, e depois olha para o que ficou."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.saida = Path(tempfile.mkdtemp(prefix="kamba-modos-"))
        cls.execucao = node.correr(
            [
                "--test",
                # Um ficheiro de cada vez: o ensaio de base abre cinco ligacoes
                # e disputa um *advisory lock* por contacto; dois ficheiros em
                # paralelo disputavam-no entre si e o teste que mede «a guarda
                # esperou 150 ms» passava a medir a carga da maquina.
                "--test-concurrency=1",
                "--experimental-test-coverage",
                "--test-reporter=tap",
                "--test-reporter-destination=stdout",
                "--test-reporter=lcov",
                "--test-reporter-destination={saida}",
                *FICHEIROS,
            ],
            cls.saida / "modos.lcov",
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
        funcao da `tests_chr`, pela mesma razao medida.
        """
        linhas = cls.escrito.splitlines()
        partes: list[str] = []
        for indice, linha in enumerate(linhas):
            if re.match(r"^\s*not ok \d+ - ", linha):
                partes.append("\n".join(linhas[indice : indice + 30]))
        resumo = [l for l in linhas if re.match(r"^# (tests|pass|fail) \d+$", l)]
        return "\n\n".join([*partes, " | ".join(resumo)]) or cls.escrito[-4000:]

    def test_os_testes_dos_modos_passam(self) -> None:
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

    def test_os_grupos_de_base_de_dados_correram_todos(self) -> None:
        """Um grupo que desapareca e uma propriedade que deixou de se provar."""
        for grupo in GRUPOS:
            with self.subTest(grupo=grupo):
                self.assertIn(grupo, self.tap)

    def test_os_testes_obrigatorios_passaram(self) -> None:
        """Pelo nome, e com `ok` a frente: a letra de cada criterio."""
        for nome in TESTES_OBRIGATORIOS:
            with self.subTest(teste=nome):
                self.assertRegex(self.tap, rf"(?m)^\s*ok \d+ - {re.escape(nome)}$")

    def test_as_32_celulas_da_tabela_foram_todas_afirmadas(self) -> None:
        """O criterio 1 pede teste **exaustivo** da tabela, nao uma amostra.

        Cada celula tem um teste com o seu nome (`<modo> + <gatilho> = ...`), e o
        que esta assercao faz e contar os que passaram: 4 modos x 8 gatilhos sao
        32, e qualquer numero menor significa que alguem trocou a enumeracao por
        uma amostra. Uma lista de nomes em `TESTES_OBRIGATORIOS` nao servia —
        eram 32 linhas a repetir o que o ficheiro TypeScript ja enumera.
        """
        celulas = re.findall(
            r"(?m)^\s*ok \d+ - (bot|dono|humano|pausada) \+ \w+ = ", self.tap
        )
        self.assertEqual(
            len(celulas),
            32,
            f"passaram {len(celulas)} celulas das 32; por modo: "
            f"{ {m: celulas.count(m) for m in ('bot', 'dono', 'humano', 'pausada')} }",
        )

    def test_a_medicao_da_corrida_saiu_no_registo(self) -> None:
        """O numero tem de aparecer **e tem de se poder ler** no registo do gate.

        O `console.log` do ensaio vai para o TAP, que esta suite captura e nao
        reimprime: sem este `print`, o numero existia e ninguem o via — e e ele
        que a seccao de verificacao do ticket cita. E a licao que a `tests_chr`
        escreveu para a latencia do `resolve`.
        """
        medidas = re.findall(r"\[KAM-018\][^\n]*", self.escrito)
        for linha in medidas:
            print(f"    {linha.strip()}")
        self.assertRegex(
            self.escrito,
            r"\[KAM-018\] 100 intercalacoes \(semente 0x[0-9a-f]+\): "
            r"\d+ passaram, \d+ suprimidas; echo primeiro \d+ \(0 enviadas\), "
            r"guarda primeiro \d+",
        )

    def test_a_cobertura_do_modulo_e_pelo_menos_a_do_estrato_critico(self) -> None:
        """O gate 4 nao tem base de dados; a cobertura de `src/modos/` mede-se aqui.

        O limiar e **lido** de `ci/thresholds.yaml`, do estrato `critico`, e nao
        escrito aqui: dois numeros em dois sitios divergem. Os modos entram nesse
        estrato pela mesma razao que o CHR — e o `tenant_id` do contexto que
        decide quem tem a palavra, e `specs/01` §4.1 poe o isolamento de tenant
        la — e por uma segunda que e deste ticket: e o unico codigo que escreve
        `conversations.mode`, e um defeito aqui e o assistente a interromper uma
        pessoa.
        """
        lcov = self.saida / "modos.lcov"
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
            # para a latencia do `resolve`: um numero que so aparece quando o
            # teste falha e um numero que a seccao de verificacao do ticket nao
            # pode citar. Vai para o registo do gate, em todas as execucoes.
            print(
                f"    [KAM-018] cobertura src/modos/{ficheiro}: "
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
