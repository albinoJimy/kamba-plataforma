"""A comparacao com o ramo principal, contra um git de verdade (KAM-007, CA3).

O `test_diff.py` prova o classificador com pares de schemas em memoria. Isto
prova a outra metade, que e a que o critério 3 nomeia — «comparacao com a
*branch* principal» — e que nenhum teste tocava: ler o contrato **como ele
esta no ramo base**, com `git ls-tree` e `git show`.

Sem isto, o classificador podia estar perfeito e o gate nunca comparar nada:
bastava o `ls-tree` devolver vazio por um caminho errado para todos os
contratos parecerem novos e toda a quebra passar. E um modo de falha que o
canario nao apanha, porque o canario nao fala com o git.

Cada teste constroi o seu repositorio num directorio temporario. Nao se usa o
repositorio real: um teste que dependa do estado de `origin/main` falha no dia
em que alguem funde outra coisa.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from contract_diff import base, catalogo, diff

SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["tipo", "versao", "payload"],
    "properties": {
        "tipo": {"type": "string", "const": "order.paid"},
        "versao": {"type": "integer", "const": 1},
        "payload": {
            "type": "object",
            "additionalProperties": False,
            "required": ["order_id"],
            "properties": {
                "order_id": {"type": "string", "format": "uuid"},
                "motivo": {"type": "string"},
            },
        },
    },
}


class ComRepositorio(unittest.TestCase):
    """Um repositorio git com um contrato commitado no ramo `principal`."""

    def setUp(self) -> None:
        self.raiz = Path(tempfile.mkdtemp(prefix="kamba-base-"))
        self.addCleanup(lambda: shutil.rmtree(self.raiz, ignore_errors=True))
        self.git("init", "--initial-branch=principal")
        self.git("config", "user.email", "ensaio@kamba.ao")
        self.git("config", "user.name", "Ensaio")
        self.escrever(SCHEMA)
        self.git("add", "-A")
        self.git("commit", "-m", "contrato inicial", "--no-verify")

    def git(self, *argumentos: str) -> subprocess.CompletedProcess:
        resultado = subprocess.run(
            ["git", *argumentos], cwd=self.raiz, capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            env=dict(os.environ, MSYS_NO_PATHCONV="1", GIT_CONFIG_GLOBAL=os.devnull,
                     GIT_CONFIG_SYSTEM=os.devnull),
        )
        self.assertEqual(resultado.returncode, 0, resultado.stderr)
        return resultado

    def escrever(self, documento: dict, tipo: str = "order.paid") -> Path:
        pasta = self.raiz / catalogo.PASTA / tipo
        pasta.mkdir(parents=True, exist_ok=True)
        caminho = pasta / "v1.schema.json"
        caminho.write_text(json.dumps(documento, indent=2) + "\n", encoding="utf-8")
        return caminho


class TestLeituraDoRamoBase(ComRepositorio):
    def test_le_o_contrato_como_esta_no_ramo(self) -> None:
        anteriores = base.contratos(self.raiz, "principal")
        self.assertEqual(sorted(anteriores), [("order.paid", 1)])
        self.assertEqual(anteriores[("order.paid", 1)].documento, SCHEMA)

    def test_o_que_esta_na_copia_de_trabalho_nao_contamina_a_leitura(self) -> None:
        """A razao de ser de ler do git e nao do disco."""
        alterado = json.loads(json.dumps(SCHEMA))
        del alterado["properties"]["payload"]["properties"]["motivo"]
        self.escrever(alterado)
        anteriores = base.contratos(self.raiz, "principal")
        self.assertIn(
            "motivo", anteriores[("order.paid", 1)].documento["properties"]["payload"]["properties"]
        )

    def test_uma_remocao_na_copia_de_trabalho_e_quebrante_contra_o_ramo(self) -> None:
        """O caminho inteiro: ler do ramo, ler do disco, classificar."""
        alterado = json.loads(json.dumps(SCHEMA))
        del alterado["properties"]["payload"]["properties"]["motivo"]
        self.escrever(alterado)
        anterior = base.contratos(self.raiz, "principal")[("order.paid", 1)].documento
        actual = catalogo.todos(self.raiz)[0].documento
        (achado,) = diff.quebra(diff.comparar(anterior, actual))
        self.assertIn("desapareceu", achado.porque)

    def test_um_campo_opcional_novo_nao_quebra(self) -> None:
        alterado = json.loads(json.dumps(SCHEMA))
        alterado["properties"]["payload"]["properties"]["nota_interna"] = {"type": "string"}
        self.escrever(alterado)
        anterior = base.contratos(self.raiz, "principal")[("order.paid", 1)].documento
        actual = catalogo.todos(self.raiz)[0].documento
        self.assertEqual(diff.quebra(diff.comparar(anterior, actual)), [])

    def test_um_contrato_novo_nao_esta_no_ramo(self) -> None:
        self.escrever(SCHEMA, tipo="order.created")
        anteriores = base.contratos(self.raiz, "principal")
        self.assertNotIn(("order.created", 1), anteriores)
        na_copia = {(c.tipo, c.versao) for c in catalogo.todos(self.raiz)}
        self.assertEqual(sorted(na_copia - set(anteriores)), [("order.created", 1)])

    def test_uma_versao_nova_deixa_a_antiga_em_paz(self) -> None:
        """Quem quer quebrar escreve v2 — e o gate compara v1 com v1."""
        v2 = json.loads(json.dumps(SCHEMA))
        v2["properties"]["versao"]["const"] = 2
        del v2["properties"]["payload"]["properties"]["motivo"]
        (self.raiz / catalogo.PASTA / "order.paid" / "v2.schema.json").write_text(
            json.dumps(v2, indent=2) + "\n", encoding="utf-8"
        )
        anteriores = base.contratos(self.raiz, "principal")
        actuais = {(c.tipo, c.versao): c for c in catalogo.todos(self.raiz)}
        for chave in set(actuais) & set(anteriores):
            self.assertEqual(
                diff.quebra(diff.comparar(anteriores[chave].documento,
                                          actuais[chave].documento)),
                [], f"{chave} mudou e nao devia",
            )
        self.assertEqual(sorted(set(actuais) - set(anteriores)), [("order.paid", 2)])

    def test_um_ramo_que_nao_existe_recusa_com_a_causa(self) -> None:
        with self.assertRaises(base.BaseIndisponivelError) as apanhado:
            base.contratos(self.raiz, "nao/existe")
        self.assertIn("fetch-depth", str(apanhado.exception))

    def test_o_ramo_existir_e_pergunta_barata_e_separada(self) -> None:
        self.assertTrue(base.existe(self.raiz, "principal"))
        self.assertFalse(base.existe(self.raiz, "nao/existe"))


if __name__ == "__main__":
    unittest.main()
