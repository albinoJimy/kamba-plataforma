"""A revisao de dados das subscricoes diz o mesmo que o `registry/` (KAM-194).

As linhas de `platform.evt_subscricoes` so as escreve o `kamba_migrator`, e por
isso vem por uma revisao de dados com as linhas **escritas a mao**. Duas fontes
a dizer o mesmo divergem no dia em que alguem mexe numa so: uma `subscriptions`
nova numa vertical, ou no `registry/idx.yaml`, sem a linha correspondente, era
um evento que o publicador nunca entregava — sem erro nenhum, em lado nenhum.

Este ensaio confronta-as:

* as linhas `agr_*` da revisao sao **exactamente** as que o `consumidores()` do
  KAM-038 deriva das verticais reais (nome, tipo, versao, `exige_ordem`);
* as linhas do `idx` sao exactamente as `subscriptions` da quarta forma, com o
  `exige_ordem` derivado pela mesma regra (o prefixo `payment.`);
* a `finalidade` de cada linha esta nas `finalidades` do exemplo do contrato do
  tipo — senao o publicador nunca entregava (§7.3).

A revisao le-se pela arvore sintactica e nao por `import`: importa-la exigia o
Alembic, e o que se confronta e a constante `LINHAS`, que e o que ela escreve.
"""

from __future__ import annotations

import ast
import json
import sys
import unittest
from pathlib import Path

from kamba_agr.eventos import subscricoes

RAIZ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(RAIZ / "tools"))

from kamba_yaml import load_file  # noqa: E402

#: O nome do ficheiro sem o numero: o numero e provisorio ate a integracao.
SUFIXO = "_subscricoes_idx_e_agr.py"


def linhas_da_revisao() -> list[tuple[str, str, str, str, str]]:
    [ficheiro] = sorted((RAIZ / "db" / "migrations" / "versions").glob(f"*{SUFIXO}"))
    arvore = ast.parse(ficheiro.read_text(encoding="utf-8"))
    for no in arvore.body:
        if isinstance(no, ast.Assign) and [getattr(a, "id", None) for a in no.targets] == ["LINHAS"]:
            return [tuple(linha) for linha in ast.literal_eval(no.value)]
    raise AssertionError(f"{ficheiro.name} nao tem a constante LINHAS")


def _bool(texto: str) -> bool:
    if texto not in ("true", "false"):
        raise AssertionError(f"exige_ordem {texto!r} nao e um literal booleano do PostgreSQL")
    return texto == "true"


class TestRevisaoContraORegisto(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from test_eventos import tabela_do_registo

        cls.linhas = linhas_da_revisao()
        cls.tabela = tabela_do_registo()

    def test_as_linhas_do_agr_sao_as_que_o_registo_deriva(self) -> None:
        da_revisao = {
            (consumer, tipo, int(versao), _bool(ordem))
            for consumer, tipo, versao, _finalidade, ordem in self.linhas
            if consumer.startswith(subscricoes.PREFIXO_DO_CONSUMIDOR)
        }
        do_registo = {(c.nome, c.tipo, c.versao, c.exige_ordem) for c in self.tabela}
        self.assertEqual(da_revisao, do_registo)

    def test_as_linhas_do_idx_sao_as_da_quarta_forma(self) -> None:
        declaracao = load_file(RAIZ / "registry" / "idx.yaml")
        nome = declaracao["consumidor"]
        declaradas = {
            (nome, s["tipo"], int(s["versao"]), subscricoes.e_de_pagamento(s["tipo"]))
            for s in declaracao["subscriptions"]
        }
        da_revisao = {
            (consumer, tipo, int(versao), _bool(ordem))
            for consumer, tipo, versao, _finalidade, ordem in self.linhas
            if consumer == nome
        }
        self.assertEqual(da_revisao, declaradas)

    def test_nenhuma_linha_fica_de_fora_das_duas_fontes(self) -> None:
        declaracao = load_file(RAIZ / "registry" / "idx.yaml")
        for consumer, *_ in self.linhas:
            with self.subTest(consumer=consumer):
                self.assertTrue(
                    consumer == declaracao["consumidor"]
                    or consumer.startswith(subscricoes.PREFIXO_DO_CONSUMIDOR),
                    "uma linha que nenhuma fonte declara",
                )

    def test_sem_chaves_repetidas(self) -> None:
        chaves = [(consumer, tipo) for consumer, tipo, *_ in self.linhas]
        self.assertEqual(len(chaves), len(set(chaves)))

    def test_a_finalidade_esta_nas_do_contrato(self) -> None:
        for consumer, tipo, _versao, finalidade, _ordem in self.linhas:
            with self.subTest(consumer=consumer, tipo=tipo):
                exemplo = json.loads(
                    (RAIZ / "contratos" / "eventos" / tipo / "exemplo.json").read_text(encoding="utf-8")
                )
                self.assertIn(finalidade, exemplo["finalidades"])

    def test_o_canario_uma_subscricao_a_mais_no_registo_reprova(self) -> None:
        """O ensaio morde: com uma subscricao a mais declarada, a igualdade cai."""
        do_registo = {(c.nome, c.tipo, c.versao, c.exige_ordem) for c in self.tabela}
        do_registo.add(("agr_vendedor", "order.created", 1, False))
        da_revisao = {
            (consumer, tipo, int(versao), _bool(ordem))
            for consumer, tipo, versao, _finalidade, ordem in self.linhas
            if consumer.startswith(subscricoes.PREFIXO_DO_CONSUMIDOR)
        }
        self.assertNotEqual(da_revisao, do_registo)


if __name__ == "__main__":
    unittest.main()
