"""A suite da midia recebida: corre as baterias e le a saida delas (KAM-020).

Esta suite **nao corre os testes, corre a saida deles**. As tres baterias do
gate 4 e o ensaio de base produzem TAP, e as asercoes Python aqui leem esse TAP
— confirmam que cada grupo apareceu, que cada teste obrigatorio passou **pelo
nome**, e que a cobertura de cada ficheiro de `src/med/` esta acima do limiar.

E a mesma forma do `tests_handoff` e do `tests_outbound`, e a razao e a mesma:
**um gate que conte testes nao nota que um desapareceu.** Um ficheiro que deixe
de ter o grupo «idempotencia» passa a prova se o que se medir for «os testes
passaram» — e a propriedade que ele provava deixou de se provar sem ninguem ver.

**E o que nenhuma das baterias mede**: se a API de midia da Meta se comporta
como este modulo supoe. Nao ha evidencia nenhuma dela no `E1` — nem tamanhos,
nem expiracao do URL, nem o fluxo de duas etapas, nem codigos de erro —, pelo
que o `ClienteDeMidia` entra por **porta** e tudo o que se afirma sobre ela e
*proposta*. Nenhuma porta falsa responde a essa pergunta, e e por isso que ela
nao esta aqui: responde-se com o primeiro contacto com a API real
(`ext:KAM-101`, `ext:KAM-102`).
"""

from __future__ import annotations

import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from tests.base import ComBase
from tests_media import node

# O leitor de YAML da casa vive em `tools/`, que nao esta no `sys.path` da
# suite: a mesma linha que o `tests_handoff` tem, e pela mesma razao.
sys.path.insert(0, str(node.RAIZ / "tools"))

from kamba_yaml import load_file  # noqa: E402

#: Os ficheiros de teste, pela ordem em que correm.
#:
#: Os tres primeiros nao precisam de base (correm tambem no gate 4) e estao aqui
#: pela **cobertura**: sem eles, a medida de `src/med/` nao incluiria o que eles
#: exercitam, e o limiar nao se podia aplicar por ficheiro.
FICHEIROS = (
    "tests/med.classes.test.ts",
    "tests/med.arquitectura.test.ts",
    "tests/med.pipeline.test.ts",
    "tests_bd/media.bd.test.ts",
)

#: Os grupos que **tem** de aparecer na saida, um por propriedade que a suite
#: prova. Se um desaparecer, a suite deixa de provar essa propriedade — e isso
#: tem de falhar aqui, nao passar por haver menos testes.
#:
#: Os oito primeiros sao das baterias do gate 4 (funcoes puras, a fonte e as
#: portas); os cinco ultimos sao do ensaio de base e sao os que **so** um
#: PostgreSQL prova.
GRUPOS = (
    "a traducao de wa_type em classe",
    "a allowlist (criterio 4)",
    "as respostas ao cliente sao deterministicas (criterio 4)",
    "o MED nao importa PAY nem COM (criterio 8)",
    "a recepcao de midia (criterio 1)",
    "nenhum URL da Meta e persistido (criterio 3)",
    "o URL interno assinado (criterio 5)",
    "a descarga que falha (criterio 6)",
    "a retencao do audio (criterio 7)",
    "as metricas (criterio 9)",
    "idempotencia (criterio 2)",
    "a monotonia do estado",
    "isolamento (Testes Requeridos: X-03 sobre media_assets)",
)

#: Testes que **tem** de ter corrido e passado, pelo nome. Lista curta, com os
#: que dao a letra de cada criterio e com os que so a base prova.
TESTES_OBRIGATORIOS = (
    # O que so um PostgreSQL prova.
    "**duas chamadas concorrentes: o `ON CONFLICT` da reserva**",
    "**tres chamadas sequenciais: 1 linha e 1 descarga**",
    "**a marcacao do modulo nao casa quando o estado mudou**",
    "**uma segunda marcacao nao reescreve um `armazenado`**",
    "**um `armazenado` sem `storage_ref` e recusado pela base**",
    "com o contexto de A, as midias de B nao aparecem",
    "com o contexto de A, uma escrita na midia de B nao acontece",
    "**o `urlInterna` de outro tenant nao devolve nada**",
    "**o canario nao esta em nenhuma coluna de nenhuma linha**",
    # A letra dos criterios, nas baterias do gate 4.
    "**tres chamadas dao 1 objecto e 1 linha**",
    "**a reserva e a primeira instrucao**, antes de qualquer chamada",
    "**o canario nao aparece em nada do que foi escrito**",
    "**sao tres tentativas e nao quatro**",
    "**e sao tres tambem quando e a descarga que cai**",
    "**o AGR e avisado**, e com o que ele precisa",
    "**o audio leva 24 h, e conta da criacao**",
    "**uma imagem nao leva prazo curto**",
    "**com o contexto de outro tenant a porta recusa** (X-08)",
    "**depois do TTL o URL devolve 403**",
    "**cada importacao esta na lista de permissao**",
    "**nenhum ficheiro escreve um estado de pagamento**",
    "**o sticker e imagem e nao uma quarta classe**",
    "**so PDF em documentos**, e a estreiteza e a defesa",
    "**nenhuma metrica leva identificadores**",
)

#: Os ficheiros do modulo. A cobertura mede-se em **cada um**.
FICHEIROS_DO_MODULO = (
    "classes.ts",
    "consultas.ts",
    "contrato.ts",
    "metricas.ts",
    "pipeline.ts",
    "index.ts",
)


def _cobertura(lcov: str) -> dict[str, tuple[int, int]]:
    """ficheiro de `src/med/` -> (linhas cobertas, linhas encontradas)."""
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
            if "/src/med/" in f"/{actual}":
                medidas[actual.rsplit("/", 1)[-1]] = (cobertas, encontradas)
            actual = None
    return medidas


class TestModuloDaMidia(ComBase):
    """Corre os testes em Node **uma vez**, e depois olha para o que ficou."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.saida = Path(tempfile.mkdtemp(prefix="kamba-media-"))
        cls.execucao = node.correr(
            [
                "--test",
                # Um ficheiro de cada vez: o ensaio de base conta linhas de
                # `media_assets` do tenant inteiro e a Meta falsa conta
                # descargas num contador unico — dois ficheiros em paralelo
                # veriam as contagens um do outro.
                "--test-concurrency=1",
                "--experimental-test-coverage",
                "--test-reporter=tap",
                "--test-reporter-destination=stdout",
                "--test-reporter=lcov",
                "--test-reporter-destination={saida}",
                *FICHEIROS,
            ],
            cls.saida / "media.lcov",
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

        A mesma funcao do `tests_chr`, do `tests_outbound` e do `tests_handoff`,
        e pela mesma razao medida la: o relatorio de cobertura ocupa milhares de
        linhas no fim da saida, e um `escrito[-6000:]` na mensagem de falha
        mostrava **so** isso.
        """
        linhas = cls.escrito.splitlines()
        partes: list[str] = []
        for indice, linha in enumerate(linhas):
            if re.match(r"^\s*not ok \d+ - ", linha):
                partes.append("\n".join(linhas[indice : indice + 30]))
        resumo = [l for l in linhas if re.match(r"^# (tests|pass|fail) \d+$", l)]
        return "\n\n".join([*partes, " | ".join(resumo)]) or cls.escrito[-4000:]

    def test_os_testes_da_midia_passam(self) -> None:
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

    def test_os_grupos_correram_todos(self) -> None:
        """Um grupo que desapareca e uma propriedade que deixou de se provar."""
        for grupo in GRUPOS:
            with self.subTest(grupo=grupo):
                self.assertIn(grupo, self.tap)

    def test_os_testes_obrigatorios_passaram(self) -> None:
        """Pelo nome, e com `ok` a frente: a letra de cada criterio."""
        for nome in TESTES_OBRIGATORIOS:
            with self.subTest(teste=nome):
                self.assertRegex(self.tap, rf"(?m)^\s*ok \d+ - {re.escape(nome)}$")

    def test_a_cobertura_do_modulo_e_pelo_menos_a_do_estrato(self) -> None:
        """O gate 4 nao tem base de dados; a cobertura de `src/med/` mede-se aqui.

        O limiar e **lido** de `ci/thresholds.yaml`, do estrato `restante`, e
        nao escrito aqui: dois numeros em dois sitios divergem.

        **E `restante` e nao `critico`, pela mesma decisao escrita que a saida e
        o handoff tomaram.** Os padroes que entraram no estrato `critico`
        entraram porque o DoD do ticket respectivo exigia >= 90%; o DoD do
        KAM-020 diz «cobertura >= limiar», sem numero, e alterar
        `ci/thresholds.yaml` pede **dois revisores** (o proprio ficheiro o diz).
        Nao se alarga um ficheiro de limiares para marcar uma caixa que nao pede
        o numero.
        """
        lcov = self.saida / "media.lcov"
        self.assertTrue(lcov.is_file(), f"nao houve LCOV:\n{self.escrito[-3000:]}")
        medidas = _cobertura(lcov.read_text(encoding="utf-8"))
        limiares = load_file(node.RAIZ / "ci" / "thresholds.yaml")
        minimo = next(
            int(e["minimo_linhas"])
            for e in limiares["estratos"]
            if e["nome"] == "restante"
        )
        em_falta = [f for f in FICHEIROS_DO_MODULO if f not in medidas]
        self.assertEqual(
            em_falta, [], f"sem medida: {em_falta}; medidos: {sorted(medidas)}"
        )
        for ficheiro in FICHEIROS_DO_MODULO:
            cobertas, encontradas = medidas[ficheiro]
            with self.subTest(ficheiro=ficheiro):
                if encontradas == 0:
                    continue
                percentagem = cobertas * 100 // encontradas
                print(f"    cobertura {ficheiro}: {percentagem}% ({cobertas}/{encontradas})")
                self.assertGreaterEqual(
                    percentagem,
                    minimo,
                    f"{ficheiro}: {percentagem}% < {minimo}% "
                    f"({cobertas}/{encontradas} linhas)",
                )


if __name__ == "__main__":
    unittest.main()
