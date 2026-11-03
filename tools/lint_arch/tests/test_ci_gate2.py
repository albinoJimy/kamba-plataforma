"""O *job* do gate 2 da o intervalo ao `lint-arch`, e o alvo corre os quatro passos.

Isto existe pela razao que esta escrita no canon: **nao ha *lint* de *workflows***
neste repositorio (`docs/ci.md` §7, lacuna 14). Desde o KAM-174 o gate 2 depende
de **duas** linhas de `.github/workflows/ci.yaml` e de um `fetch-depth`, e uma
alteracao a qualquer delas deixaria a leitura das mensagens a correr em modo
`sem-passagem` — verde, e sem ter lido *commit* nenhum. Nenhuma mutacao ao YAML
seria detectada por nada.

Verifica-se por texto e nao por um leitor de YAML de proposito: o que tem de
sobreviver sao estas linhas, e `tools/kamba_yaml.py` e um subconjunto que nao le
o `ci.yaml` inteiro. E a mesma forma do `test_ci_gate9.py`, que e o precedente
que o ticket manda copiar.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from lint_arch import commits

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yaml"
MAKEFILE = ROOT / "Makefile"


def _job(nome: str) -> str:
    """O bloco de um *job*, do seu nome ate ao *job* seguinte com a mesma indentacao."""
    texto = WORKFLOW.read_text(encoding="utf-8")
    inicio = texto.index(f"\n  {nome}:\n")
    resto = texto[inicio + 1 :]
    seguinte = re.search(r"\n  [a-z0-9][a-z0-9-]*:\n", resto)
    return resto[: seguinte.start()] if seguinte else resto


class TestJobDoGate2(unittest.TestCase):
    def setUp(self) -> None:
        self.bloco = _job("gate-2-tipos")

    def test_o_checkout_traz_a_historia_toda(self) -> None:
        """Sem isto nao ha historia de ramo no clone e o intervalo nao se resolve.

        O job tinha `actions/checkout@v5` **sem `with:`** — profundidade 1 por
        omissao, isto e, um commit no clone.
        """
        self.assertIn("fetch-depth: 0", self.bloco)

    def test_o_intervalo_chega_ao_gate_pelas_duas_variaveis(self) -> None:
        for variavel in ("GATE2_EVENTO:", "GATE2_MERGE_REF:"):
            self.assertIn(variavel, self.bloco, f"{variavel} em falta no job do gate 2")

    def test_o_accionamento_vai_em_bruto(self) -> None:
        self.assertIn("GATE2_EVENTO: ${{ github.event_name }}", self.bloco)

    def test_o_merge_ref_e_o_commit_que_o_job_tem_em_maos(self) -> None:
        """A linha **inteira**, e nao a expressao solta.

        E a licao do achado A3 do KAM-131: a revisao adversarial trocou os valores
        de `GATE9_BASE` e `GATE9_HEAD` entre si, as assercoes continuaram a bater
        porque procuravam as expressoes em qualquer sitio do bloco, e o gate
        passou a varrer um intervalo invertido — zero commits, «limpo». Uma
        assercao que nao diz **a qual variavel** a expressao pertence e satisfeita
        por um YAML que adivinha ao contrario.
        """
        self.assertIn("GATE2_MERGE_REF: ${{ github.sha }}", self.bloco)

    def test_as_variaveis_nao_estao_trocadas(self) -> None:
        """A mutacao exacta do A3, nomeada: o accionamento no sitio do SHA.

        As duas assercoes de cima bastariam, mas esta diz **porque** — e falha com
        a mensagem certa no dia em que alguem as troque.
        """
        self.assertNotIn("GATE2_EVENTO: ${{ github.sha }}", self.bloco)
        self.assertNotIn("GATE2_MERGE_REF: ${{ github.event_name }}", self.bloco)

    def test_cada_accionamento_fail_closed_corre_neste_workflow_ou_esta_antecipado(
        self,
    ) -> None:
        """Um accionamento fail-closed que o `on:` traga tem de ter merge ref.

        O `github.sha` serve os tres: no `pull_request` e no `pull_request_target`
        e o commit de merge de teste, e no `merge_group` e a cabeca da fila. Nao
        ha, como no gate 9, uma chave do evento diferente por accionamento — e
        por isso o que se verifica aqui e que **uma** linha os cobre a todos.
        """
        self.assertIn("GATE2_MERGE_REF: ${{ github.sha }}", self.bloco)
        for accionamento in sorted(commits.EXIGEM_COMMITS):
            self.assertIsNone(
                commits.ACCIONAMENTOS[accionamento],
                f"{accionamento} saiu de EXIGEM_COMMITS sem sair de ACCIONAMENTOS",
            )

    def test_todo_o_accionamento_do_on_esta_escrito_em_accionamentos(self) -> None:
        """A regra «um accionamento que nao esteja escrito e vermelho» tem um custo.

        Se o `on:` ganhar um accionamento que `ACCIONAMENTOS` nao tenha, o gate 2
        — que e contexto obrigatorio do *ruleset* de `main` — fica vermelho em
        **todas** as execucoes desse accionamento, sem autor que o possa
        corrigir. E a armadilha que o gate 9 escreveu no YAML com a linha do
        `merge_group`; aqui apanha-se por teste.
        """
        texto = WORKFLOW.read_text(encoding="utf-8")
        inicio = texto.index("\non:\n")
        resto = texto[inicio + 1 :]
        seguinte = re.search(r"\n[a-z][a-z_-]*:\n", resto)
        bloco_on = resto[: seguinte.start()] if seguinte else resto
        # As chaves de primeiro nivel do `on:`, que sao os accionamentos.
        no_on = set(re.findall(r"^  ([a-z_]+):?$", bloco_on, re.M))
        self.assertTrue(no_on, bloco_on)
        em_falta = no_on - set(commits.ACCIONAMENTOS)
        self.assertEqual(
            em_falta,
            set(),
            f"accionamentos no `on:` que `ACCIONAMENTOS` nao escreve: {sorted(em_falta)}. "
            "O gate 2 ficaria vermelho em todas as execucoes deles.",
        )

    def test_o_yaml_nao_decide_o_modo(self) -> None:
        """A decisao vive em `decidir_intervalo`, que tem testes; aqui nao.

        Um `if` neste job seria logica sem *lint* e sem teste.
        """
        self.assertNotIn("if:", self.bloco)

    def test_o_job_continua_a_bloquear_pelo_resumo(self) -> None:
        texto = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("      - gate-2-tipos\n", texto)


class TestSemJobNovo(unittest.TestCase):
    """Criterio 1 e a DoD: `esperados` e os `needs:` do agregador inalterados.

    Um *job* novo acrescenta um contexto exigido ao *ruleset* de `main`, e isso e
    alteracao de regra de bloqueio — decisao do fundador. O KAM-174 entra no gate
    2 precisamente para nao o fazer, e isto e o que o prende.
    """

    def test_o_agregador_continua_a_esperar_onze_gates(self) -> None:
        texto = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("esperados=11", texto)

    def test_nenhum_job_novo_entrou_no_needs_do_agregador(self) -> None:
        texto = WORKFLOW.read_text(encoding="utf-8")
        inicio = texto.index("      - gate-2-tipos\n")
        bloco = texto[inicio - 200 : inicio + 500]
        nomes = set(re.findall(r"^      - (gate-[a-z0-9-]+)$", bloco, re.M))
        # Os onze do `needs`, que sao os que o `esperados=11` conta. Esta lista e
        # escrita a mao de proposito, como o `esperados`: um gate novo que entre
        # no `needs` e nao entre aqui faz este teste falhar, e quem o acrescentou
        # vem ler porque.
        self.assertEqual(
            nomes,
            {
                "gate-1-build",
                "gate-2-tipos",
                "gate-3-referencias",
                "gate-3b-nomes-canonicos",
                "gate-3c-backlog",
                "gate-4-unit",
                "gate-6-isolamento",
                "gate-7-contratos",
                "gate-8-migracoes",
                "gate-9-segredos",
                "gate-11-supply-chain",
            },
        )


class TestAlvoLintArch(unittest.TestCase):
    def setUp(self) -> None:
        texto = MAKEFILE.read_text(encoding="utf-8")
        inicio = texto.index("\nlint-arch:\n")
        resto = texto[inicio + 1 :]
        seguinte = re.search(r"\n## ", resto)
        self.receita = resto[: seguinte.start()] if seguinte else resto

    def test_corre_a_leitura_das_mensagens_e_o_seu_canario(self) -> None:
        self.assertIn("commit-range", self.receita)
        self.assertIn("commit-range-canario", self.receita)

    def test_passa_as_duas_variaveis_ao_subcomando(self) -> None:
        for variavel in ("$(GATE2_EVENTO)", "$(GATE2_MERGE_REF)"):
            self.assertIn(variavel, self.receita)

    def test_a_leitura_nao_entra_no_all(self) -> None:
        """O `all` corre em `make check` e em cada execucao local.

        Meter-lhe dentro um varrimento que precisa de um intervalo de commits
        faria um comando local depender de estado de CI. E um subcomando proprio,
        e a decisao esta escrita no `Makefile`.
        """
        from lint_arch import cli

        self.assertIn("commit-range", cli.__doc__ or "")
        # O `all` nao o inclui: a sua linha de ajuda enumera o que ele corre.
        linha_do_all = next(
            (
                linha
                for linha in (cli.__doc__ or "").splitlines()
                if " all " in linha and "lint_arch" in linha
            ),
            "",
        )
        self.assertNotIn("commit-range", linha_do_all)

    def test_os_quatro_passos_correm_todos(self) -> None:
        """Uma falha em qualquer um deles falha o alvo: sao quatro receitas."""
        linhas = [
            linha
            for linha in self.receita.splitlines()
            if linha.startswith("\t@$(PYTHON) -m lint_arch")
        ]
        self.assertEqual(len(linhas), 4, self.receita)


class TestAlvoCi2(unittest.TestCase):
    def setUp(self) -> None:
        texto = MAKEFILE.read_text(encoding="utf-8")
        inicio = texto.index("\nci-2:\n")
        resto = texto[inicio + 1 :]
        seguinte = re.search(r"\n# --- ", resto)
        self.receita = resto[: seguinte.start()] if seguinte else resto

    def test_o_ci_2_continua_a_chamar_o_lint_arch(self) -> None:
        """E por aqui que a leitura das mensagens entra no gate 2."""
        self.assertIn("$(MAKE) lint-arch", self.receita)


if __name__ == "__main__":
    unittest.main()
