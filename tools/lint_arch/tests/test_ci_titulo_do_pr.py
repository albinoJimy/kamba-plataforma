"""O *job* que verifica o titulo do PR corre no evento certo, e corre o canario.

Isto existe pela razao escrita no canon: **nao ha *lint* de *workflows*** neste
repositorio (`docs/ci.md` §7, lacuna 15). A verificacao do KAM-164 depende de
quatro linhas de `.github/workflows/titulo-do-pr.yaml` — os `types` do evento, o
`name` do *job* (que **e** o nome do contexto de CI), o passo que corre o
`pr-title` e o passo que corre o canario. Uma alteracao a qualquer delas deixa a
verificacao verde sem verificar nada, ou com nome de contexto que o *ruleset*
nunca encontra, e nenhuma mutacao ao YAML seria detectada por nada.

Verifica-se por **texto** e nao por um leitor de YAML, de proposito e com
medicao: `tools/kamba_yaml.py` e um subconjunto e nao le nem este ficheiro nem o
`ci.yaml` — os dois usam listas em estilo de fluxo (`branches: [main]`), que o
subconjunto recusa (medido a 2026-11-03: `linha 84` aqui, `linha 26` no `ci.yaml`).

Asserta-se a **linha inteira**, com o nome da variavel ou da chave. A licao esta
paga em `test_ci_gate9.py`: a primeira versao desse ficheiro procurava as
expressoes «em qualquer sitio do bloco», a revisao adversarial trocou duas
variaveis de sitio, e as asercoes continuaram verdes.
"""

from __future__ import annotations

import io
import os
import re
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from lint_arch import cli

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github" / "workflows" / "titulo-do-pr.yaml"
CI = ROOT / ".github" / "workflows" / "ci.yaml"
ESPELHO = ROOT / ".github" / "rulesets" / "main.json"
MAKEFILE = ROOT / "Makefile"

#: O nome do contexto de CI, escrito aqui tambem. **Nao e redundancia**: e o
#: terceiro ponto que torna um erro de copia visivel, no padrao do KAM-157. Os
#: outros dois sao o `name:` do *job* e — quando o fundador o acrescentar — a
#: entrada do *ruleset*. Com dois, uma alteracao em ambos passa; com tres, e
#: preciso enganar-se em todos.
CONTEXTO = "titulo do PR — forma convencional"

#: O *job* e o comando, nos nomes que o YAML tem de continuar a ter.
JOB = "forma-do-titulo"
COMANDO = "python -m lint_arch --root .. pr-title"
COMANDO_CANARIO = "python -m lint_arch --root .. pr-title-canario"


def _texto() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _job(nome: str) -> str:
    """O bloco de um *job*, do seu nome ate ao *job* seguinte com a mesma indentacao."""
    texto = _texto()
    inicio = texto.index(f"\n  {nome}:\n")
    resto = texto[inicio + 1 :]
    seguinte = re.search(r"\n  [a-z0-9][a-z0-9-]*:\n", resto)
    return resto[: seguinte.start()] if seguinte else resto


class TestOEventoDoTitulo(unittest.TestCase):
    """Criterio 3: corre em `pull_request`, e com `edited`."""

    def test_o_ficheiro_existe(self) -> None:
        self.assertTrue(WORKFLOW.is_file(), f"{WORKFLOW} em falta")

    def test_corre_em_pull_request_sobre_main(self) -> None:
        texto = _texto()
        self.assertIn("\non:\n  pull_request:\n", texto)
        self.assertIn("\n    branches: [main]\n", texto)

    def test_os_quatro_types_estao_declarados_na_mesma_linha(self) -> None:
        # A linha inteira: uma lista reordenada passa, uma lista a que falte um
        # `type` nao. O `edited` e o que importa — sem ele, um titulo emendado
        # depois de os portoes ficarem verdes nunca e reavaliado, e com
        # `allow_auto_merge` ligado (2026-10-27) a fusao acontece sem ninguem a
        # olhar.
        self.assertIn(
            "\n    types: [opened, edited, reopened, synchronize]\n", _texto()
        )

    def test_nao_corre_em_push(self) -> None:
        # Em `push` nao ha `github.event.pull_request.title`: a expressao avalia
        # a cadeia **vazia** e a variavel de ambiente fica definida, pelo que o
        # passo sairia **1** («titulo de PR vazio») e nao 2 — tambem
        # fail-closed, mas por outro caminho. O `exit=2` e o caso de a variavel
        # nao existir, que a partir deste *workflow* e inalcancavel. A primeira
        # versao deste comentario dizia 2, e a revisao adversarial mediu-o.
        self.assertNotIn("\n  push:\n", _texto())


class TestOJobEOContexto(unittest.TestCase):
    """Criterio 4: o nome do *job* e o nome do contexto, e o *job* nao e decorativo."""

    def test_o_nome_do_job_e_o_contexto(self) -> None:
        self.assertIn(f'\n    name: "{CONTEXTO}"\n', _job(JOB))

    def test_o_job_nao_tem_continue_on_error(self) -> None:
        # E o que distingue «ligado» de «ligado a fingir» — a frase e do
        # comentario do `gates-reservados` no `ci.yaml`.
        self.assertNotIn("continue-on-error", _job(JOB))

    def test_o_contexto_ainda_nao_esta_no_espelho_do_ruleset(self) -> None:
        """Enquanto o fundador nao o aplicar, o espelho nao o pode afirmar.

        Escrever o contexto so no `.github/rulesets/main.json` poe o
        `make ruleset` vermelho com `contexto-so-no-ficheiro` e torna o espelho
        **falso**, que e pior do que a lacuna — foi a escolha dos *gates* 3b e 3c
        pela mesma razao (`docs/ci.md` §7, lacuna 17). Quando o contexto for
        acrescentado ao *ruleset* no GitHub **e** ao espelho, este teste tem de
        ser invertido no mesmo PR, e e isso que ele esta aqui a exigir: que
        ninguem mexa num lado sem mexer no outro.
        """
        self.assertNotIn(
            CONTEXTO,
            ESPELHO.read_text(encoding="utf-8"),
            "o contexto entrou no espelho: inverta este teste e confirme que o "
            "ruleset no GitHub tambem o tem (make ruleset)",
        )

    def test_o_job_nao_entrou_na_conta_do_agregador_do_ci(self) -> None:
        # O `gates-em-ambito` do `ci.yaml` conta os `needs` a mao
        # (`esperados=11`). Este *job* vive noutro *workflow* e nao entra la — se
        # alguem o mudar de sitio, esta linha diz-lhe que a conta tambem muda.
        ci = CI.read_text(encoding="utf-8")
        self.assertNotIn(JOB, ci)
        self.assertIn("          esperados=11\n", ci)


class TestOsDoisPassos(unittest.TestCase):
    """Criterio 5: a verificacao corre, e o canario corre ao lado dela."""

    def test_corre_o_pr_title_de_dentro_de_tools(self) -> None:
        bloco = _job(JOB)
        self.assertIn("        working-directory: tools\n", bloco)
        self.assertIn(f"        run: {COMANDO}\n", bloco)

    def test_corre_o_canario(self) -> None:
        self.assertIn(f"        run: {COMANDO_CANARIO}\n", _job(JOB))

    def test_o_canario_corre_sempre(self) -> None:
        # Sem `if: always()`, um titulo conforme deixava o canario sem correr, e
        # a prova de que a verificacao morde voltava a viver so num `unittest` —
        # que foi como o *gate* 9 esteve sete PR sem nada que o provasse.
        bloco = _job(JOB)
        posicao = bloco.index(COMANDO_CANARIO)
        self.assertIn("if: always()", bloco[:posicao])


class TestOTituloNaoPassaPeloShell(unittest.TestCase):
    """O titulo e texto de terceiros, e nao se interpola num comando.

    `${{ github.event.pull_request.title }}` dentro de um `run:` e injeccao de
    *shell* na maquina do CI: o GitHub substitui a expressao **antes** de o
    *shell* ver a linha, pelo que um titulo com `; curl …` corre. Pelo ambiente,
    o *shell* nunca o ve.
    """

    def test_o_titulo_chega_por_variavel_de_ambiente(self) -> None:
        # O nome vem da constante do `cli`, e nao escrito a mao: escrito a mao,
        # renomear a constante no Python deixava este teste verde e o *workflow*
        # a passar o nome velho. Achado da revisao adversarial do KAM-164.
        bloco = _job(JOB)
        self.assertIn(
            f"          {cli.AMBIENTE_TITULO_PR}: "
            "${{ github.event.pull_request.title }}\n",
            bloco,
        )

    def test_nenhum_run_interpola_uma_expressao(self) -> None:
        maus = [
            linha
            for linha in _texto().splitlines()
            if re.match(r"\s*(run|-\s*run):", linha) and "${{" in linha
        ]
        self.assertEqual(maus, [], f"expressao interpolada num run: {maus}")

    def test_o_titulo_nao_se_le_em_mais_nenhum_sitio(self) -> None:
        # Uma segunda leitura do titulo (num `echo`, num `::notice`) era um
        # segundo caminho por onde ele chegava ao *shell*. Os comentarios do
        # cabecalho ficam de fora da conta: la o nome do campo e explicacao, nao
        # leitura.
        leituras = [
            linha
            for linha in _texto().splitlines()
            if "github.event.pull_request.title" in linha
            and not linha.lstrip().startswith("#")
        ]
        self.assertEqual(
            len(leituras),
            1,
            f"o titulo le-se uma vez, para a variavel de ambiente: {leituras}",
        )


class TestOCanarioCorreNoGate2(unittest.TestCase):
    """O canario prova que a verificacao morde; isto prova que ele e chamado.

    E a camada de cima, no molde de
    `tools/supply_chain/tests/test_revisao_adversarial.py`. O canario entra no
    alvo `lint-arch`, que o `make ci-2` corre: assim a prova de que a verificacao
    morde **nao** depende do GitHub, que e o que o §1 do `docs/ci.md` pede, e
    entra num *gate* que ja e contexto exigido em vez de abrir *job* novo.
    Achado da revisao adversarial do KAM-164.
    """

    def setUp(self) -> None:
        self.texto = MAKEFILE.read_text(encoding="utf-8")

    def receita(self, alvo: str) -> str:
        correspondencia = re.search(
            rf"(?m)^{re.escape(alvo)}:[^\n]*\n((?:\t[^\n]*\n)+)", self.texto
        )
        self.assertIsNotNone(correspondencia, f"alvo {alvo} sem receita")
        assert correspondencia is not None
        return "\n".join(
            linha
            for linha in correspondencia.group(1).split("\n")
            if not linha.strip().startswith("@#")
        )

    def test_o_lint_arch_corre_o_all_e_o_canario(self) -> None:
        receita = self.receita("lint-arch")
        self.assertIn("-m lint_arch --root $(ROOT) all", receita)
        self.assertIn("-m lint_arch --root $(ROOT) pr-title-canario", receita)

    def test_o_gate_2_chama_o_lint_arch(self) -> None:
        self.assertIn("$(MAKE) lint-arch", self.receita("ci-2"))

    def test_o_gate_2_nao_verifica_o_titulo_do_PR(self) -> None:
        """O titulo **nao** cabe no *gate* 2, e isso tem de continuar verdade.

        O titulo chega pelo evento do PR e nao pelo ramo: um `pr-title` dentro do
        `make ci-2` sairia 2 por falta de titulo em `main`, ou — pior — alguem
        punha-lhe um valor por omissao e o *gate* ficava verde sem verificar
        nada.
        """
        receita = self.receita("lint-arch")
        self.assertNotIn("pr-title\n", receita)
        self.assertNotIn("pr-title ", receita)


class TestASuperficieDaLinhaDeComando(unittest.TestCase):
    """O `pr-title` e o `pr-title-canario`, pela CLI e com o codigo de saida.

    Sem isto, trocar o `return 2` por `return 0` — ou dar um valor por omissao a
    variavel de ambiente — deixava os testes **e** o passo de CI verdes tendo
    verificado nada, que e a definicao do defeito que este ticket abre. Era o
    unico sitio do diff onde a logica nova nao estava presa por nada. Achado da
    revisao adversarial do KAM-164.
    """

    CONFORME = "feat(KAM-164): verifica o titulo do PR contra a convencao"
    #: O assunto que o `29778f3` deixou no `main`, sem o ` (#75)` do GitHub.
    RECUSADO = "KAM-038 — Subscricao de eventos: as verticais acordam por evento"

    def correr(self, argv: list[str], ambiente: str | None) -> tuple[int, str, str]:
        anterior = os.environ.get(cli.AMBIENTE_TITULO_PR)
        if ambiente is None:
            os.environ.pop(cli.AMBIENTE_TITULO_PR, None)
        else:
            os.environ[cli.AMBIENTE_TITULO_PR] = ambiente
        saida, erro = io.StringIO(), io.StringIO()
        try:
            with redirect_stdout(saida), redirect_stderr(erro):
                codigo = cli.main(["--root", str(ROOT), *argv])
        finally:
            if anterior is None:
                os.environ.pop(cli.AMBIENTE_TITULO_PR, None)
            else:
                os.environ[cli.AMBIENTE_TITULO_PR] = anterior
        return codigo, saida.getvalue(), erro.getvalue()

    def test_titulo_conforme_no_ambiente_sai_0(self) -> None:
        codigo, saida, _ = self.correr(["pr-title"], self.CONFORME)
        self.assertEqual(codigo, 0)
        self.assertIn("titulo do PR: conforme", saida)

    def test_titulo_conforme_no_argumento_sai_0(self) -> None:
        # O argumento ganha ao ambiente: e a via de quem corre isto a mao.
        codigo, _, _ = self.correr(["pr-title", self.CONFORME], "lixo que nao conta")
        self.assertEqual(codigo, 0)

    def test_titulo_fora_da_forma_sai_1_com_a_ajuda_inteira(self) -> None:
        codigo, _, erro = self.correr(["pr-title"], self.RECUSADO)
        self.assertEqual(codigo, 1)
        for pedaco in (
            "titulo fora de",
            "Titulo recusado:",
            "Formato esperado:",
            "Exemplo:",
            "Tipos:",
            "squash_merge_commit_title",
            "tools/conventions.json",
        ):
            with self.subTest(pedaco=pedaco):
                self.assertIn(pedaco, erro)

    def test_sem_variavel_sai_2_e_nao_0(self) -> None:
        # Fail-closed. Um passo de CI a que a variavel falhasse ficaria verde sem
        # ter verificado nada.
        codigo, _, erro = self.correr(["pr-title"], None)
        self.assertEqual(codigo, 2)
        self.assertIn("titulo do PR em falta", erro)
        self.assertIn(cli.AMBIENTE_TITULO_PR, erro)

    def test_variavel_vazia_sai_1_e_nao_0(self) -> None:
        # E o caso real de um evento sem `pull_request`: a expressao avalia a
        # cadeia vazia e a variavel **fica** definida.
        codigo, _, erro = self.correr(["pr-title"], "")
        self.assertEqual(codigo, 1)
        self.assertIn("titulo de PR vazio", erro)

    def test_a_ajuda_ecoa_o_titulo_normalizado_e_nao_o_cru(self) -> None:
        # Um titulo com nova linha seguida de `::error` chegava ao registo do
        # *runner* no inicio de linha, onde o GitHub o le como *workflow command*.
        cru = "KAM-038 titulo mau\n::error title=INJECTADO::o canario foi desligado"
        codigo, _, erro = self.correr(["pr-title"], cru)
        self.assertEqual(codigo, 1)
        self.assertNotIn("\n::error", erro)
        self.assertIn("KAM-038 titulo mau ::error", erro)

    def test_o_canario_corre_pela_cli_e_sai_0(self) -> None:
        codigo, saida, _ = self.correr(["pr-title-canario"], None)
        self.assertEqual(codigo, 0)
        self.assertIn("pr-title canario:", saida)
        self.assertIn("0 falha(s)", saida)
