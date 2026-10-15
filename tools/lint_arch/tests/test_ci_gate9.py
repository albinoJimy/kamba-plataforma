"""O *job* do gate 9 da o intervalo ao varrimento, e o `make ci-9` corre as duas passagens.

Isto existe por uma razao escrita no canon: **nao ha *lint* de *workflows***
neste repositorio (`docs/ci.md` §7). O gate 9 passou a depender de tres linhas
de `.github/workflows/ci.yaml` e de um `fetch-depth`, e uma alteracao a qualquer
delas deixaria a segunda passagem a correr em modo `so-arvore` — verde, e sem
varrer nada da historia. Nenhuma mutacao ao YAML seria detectada por nada.

Verifica-se por texto e nao por um leitor de YAML de proposito: o que tem de
sobreviver sao estas linhas, e `tools/kamba_yaml.py` e um subconjunto que nao
le o `ci.yaml` inteiro (`docs/ci.md` §7, lacuna 14).
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

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


class TestJobDoGate9(unittest.TestCase):
    def setUp(self) -> None:
        self.bloco = _job("gate-9-segredos")

    def test_o_checkout_traz_a_historia_toda(self) -> None:
        """Sem isto o SHA de base nao chega ao clone e o gate fica vermelho."""
        self.assertIn("fetch-depth: 0", self.bloco)

    def test_o_intervalo_chega_ao_gate_pelas_tres_variaveis(self) -> None:
        for variavel in ("GATE9_EVENTO:", "GATE9_BASE:", "GATE9_HEAD:"):
            self.assertIn(variavel, self.bloco, f"{variavel} em falta no job do gate 9")

    def test_a_base_vem_do_evento_e_nao_e_adivinhada(self) -> None:
        """A linha **inteira**, e nao as expressoes soltas.

        A primeira versao destas assercoes procurava
        `github.event.pull_request.base.sha` e `github.sha` em qualquer sitio do
        bloco. A revisao adversarial trocou os valores de `GATE9_BASE` e
        `GATE9_HEAD` entre si: as quatro assercoes continuaram a bater, a
        bateria ficou verde, e o gate passou a varrer um intervalo invertido —
        zero commits, zero blobs, «limpo» (A3). Uma assercao que nao diz **a
        qual variavel** a expressao pertence e satisfeita por um YAML que
        adivinha ao contrario.

        Cada accionamento com intervalo traz a base na sua chave, e e por isso
        que sao tres na mesma linha.
        """
        self.assertIn(
            "GATE9_BASE: ${{ github.event.pull_request.base.sha "
            "|| github.event.merge_group.base_sha || github.event.before }}",
            self.bloco,
        )

    def test_a_cabeca_e_o_commit_que_o_job_tem_em_maos(self) -> None:
        self.assertIn("GATE9_HEAD: ${{ github.sha }}", self.bloco)

    def test_o_accionamento_vai_em_bruto(self) -> None:
        self.assertIn("GATE9_EVENTO: ${{ github.event_name }}", self.bloco)

    def test_cada_accionamento_fail_closed_traz_a_sua_chave_de_base(self) -> None:
        """Um accionamento fail-closed sem chave na cadeia e uma armadilha.

        `merge_group` nao esta no `on:` de hoje, mas esta em `SEM_INTERVALO` como
        fail-closed: no dia em que a fila de merge se ligar, sem a chave do
        evento na cadeia o gate 9 ficava vermelho em **todas** as execucoes (A10).
        """
        from scan_secrets.historia import SEM_INTERVALO

        chaves = {
            "pull_request": "github.event.pull_request.base.sha",
            "pull_request_target": "github.event.pull_request.base.sha",
            "merge_group": "github.event.merge_group.base_sha",
        }
        for accionamento, razao in SEM_INTERVALO.items():
            if razao is not None:
                continue
            chave = chaves.get(accionamento)
            self.assertIsNotNone(
                chave,
                f"{accionamento} entrou em SEM_INTERVALO como fail-closed e "
                "ninguem disse de que chave do evento vem a sua base",
            )
            self.assertIn(
                chave,
                self.bloco,
                f"{accionamento} e fail-closed e a sua chave de base nao vai no job",
            )

    def test_o_yaml_nao_decide_o_modo(self) -> None:
        """A decisao vive em `decidir_intervalo`, que tem testes; aqui nao.

        Um `if` neste job seria logica sem *lint* e sem teste — e foi assim que
        a lacuna 9 ficou aberta desde o KAM-002.
        """
        self.assertNotIn("if:", self.bloco)

    def test_o_job_continua_a_bloquear_pelo_resumo(self) -> None:
        texto = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("      - gate-9-segredos\n", texto)


class TestAlvoCi9(unittest.TestCase):
    def setUp(self) -> None:
        texto = MAKEFILE.read_text(encoding="utf-8")
        inicio = texto.index("\nci-9:\n")
        resto = texto[inicio + 1 :]
        seguinte = re.search(r"\n## ", resto)
        self.receita = resto[: seguinte.start()] if seguinte else resto

    def test_corre_as_duas_passagens(self) -> None:
        self.assertIn("'tree'", self.receita)
        self.assertIn("'history'", self.receita)

    def test_passa_as_tres_variaveis_ao_subcomando(self) -> None:
        for variavel in ("$(GATE9_EVENTO)", "$(GATE9_BASE)", "$(GATE9_HEAD)"):
            self.assertIn(variavel, self.receita)

    def test_nenhuma_passagem_substitui_a_outra(self) -> None:
        """As duas passagens sao duas receitas: uma falha e o alvo falha.

        A terceira invocacao do `scan_secrets` nesta receita e a prova do
        canario, que corre dentro de um *subshell* e conta achados — por isso se
        contam as linhas de receita e nao as invocacoes.
        """
        linhas = [
            l for l in self.receita.splitlines() if l.startswith("\t@$(PYTHON) -c")
        ]
        self.assertEqual(len(linhas), 2, self.receita)
        for linha in linhas:
            self.assertIn("sys.exit(main(", linha)


if __name__ == "__main__":
    unittest.main()
