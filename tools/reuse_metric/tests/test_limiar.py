"""Os casos limite do limiar, e os codigos de saida (KAM-039).

Os *Testes Requeridos* do bloco pedem-nos a letra: «*script* de reuso com
repositorio de exemplo (casos limite: 69,9% falha, 70,0% passa)». E o pedido
tem razao de ser: um limiar que se escreve `>` em vez de `>=` reprova um
resultado exactamente no limite, e a diferenca nunca aparece num repositorio
real porque nenhum da 70,00% redondos.

Por isso os dois casos medem-se sobre **ficheiros a serio**, numa arvore cujos
tamanhos sao escolhidos para a conta cair em 1000 linhas:

```text
A   especifico 300, partilhado 700   ->  70,00%   passa, saida 0
B   especifico 301, partilhado 699   ->  69,90%   falha, saida 1
```
"""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from reuse_metric.cli import principal
from reuse_metric.tests import arvore

#: Os tamanhos que fazem a conta cair em 1000 linhas. O `especifico` e
#: `grafo + migracao_nova + 1` (o `__init__.py` da vertical) e o `partilhado` e
#: `nucleo + 2 x simbolo + migracao_base`.
NO_LIMIAR = {"especifico": 294, "nucleo": 680}
ABAIXO = {"especifico": 295, "nucleo": 679}


class _ComArvore(unittest.TestCase):
    def montar(self, **tamanhos) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return arvore.montar(Path(tmp.name), **tamanhos)

    def correr(self, raiz: Path, *extra: str) -> tuple[int, dict, str]:
        destino = raiz / "saida.json"
        saida, erro = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(saida), contextlib.redirect_stderr(erro):
            codigo = principal(
                ["--root", str(raiz), "--json", str(destino), "medir", *extra]
            )
        mapa = json.loads(destino.read_text(encoding="utf-8")) if destino.exists() else {}
        return codigo, mapa, saida.getvalue() + erro.getvalue()


class TestOsCasosLimite(_ComArvore):
    def test_setenta_exacto_passa(self) -> None:
        raiz = self.montar(**NO_LIMIAR)
        codigo, mapa, _ = self.correr(raiz)
        self.assertEqual(mapa["loc_especifico"], 300)
        self.assertEqual(mapa["loc_total"], 1000)
        self.assertEqual(mapa["reuso_pct"], 70.0)
        self.assertEqual(codigo, 0, "70,00% tem de passar: o limiar e `>=`")

    def test_sessenta_e_nove_virgula_nove_falha(self) -> None:
        raiz = self.montar(**ABAIXO)
        codigo, mapa, texto = self.correr(raiz)
        self.assertEqual(mapa["loc_especifico"], 301)
        self.assertEqual(mapa["loc_total"], 1000)
        self.assertEqual(mapa["reuso_pct"], 69.9)
        self.assertEqual(codigo, 1)
        self.assertIn("ACHADO", texto)
        self.assertIn("abaixo do limiar", texto)

    def test_uma_linha_de_codigo_decide(self) -> None:
        """**A sensibilidade, medida.** Os dois casos diferem numa linha.

        E o que prova que o limite esta mesmo no limite: nao e uma margem de
        doze vezes a dizer que passa.
        """
        _, no_limiar, _ = self.correr(self.montar(**NO_LIMIAR))
        _, abaixo, _ = self.correr(self.montar(**ABAIXO))
        self.assertEqual(abaixo["loc_especifico"] - no_limiar["loc_especifico"], 1)
        self.assertEqual(abaixo["loc_total"], no_limiar["loc_total"])


class TestOLimiarSobreposto(_ComArvore):
    def test_o_limiar_da_linha_de_comandos_ganha_ao_declarado(self) -> None:
        raiz = self.montar(**NO_LIMIAR)
        self.assertEqual(self.correr(raiz, "--limiar", "70.01")[0], 1)
        self.assertEqual(self.correr(raiz, "--limiar", "69")[0], 0)


class TestCodigosDeSaida(_ComArvore):
    def test_declaracao_em_falta_sai_com_dois(self) -> None:
        """`2` e malformado e `1` e achado: confundi-los lia-se como «passou»."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        saida, erro = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(saida), contextlib.redirect_stderr(erro):
            codigo = principal(["--root", tmp.name, "medir"])
        self.assertEqual(codigo, 2)
        self.assertIn("nao existe", erro.getvalue())

    def test_declaracao_malformada_sai_com_dois(self) -> None:
        raiz = self.montar(declaracao="version: 1\n")
        saida, erro = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(saida), contextlib.redirect_stderr(erro):
            codigo = principal(["--root", str(raiz), "nucleo"])
        self.assertEqual(codigo, 2)


class TestOArtefacto(_ComArvore):
    def test_o_json_e_byte_a_byte_igual_em_duas_execucoes(self) -> None:
        """O criterio 6: «o resultado e reproduzivel (2 execucoes iguais)».

        Compara-se o **ficheiro** e nao o mapa: a ordem das chaves e das listas
        tambem tem de ser estavel, senao o artefacto de duas corridas do CI
        difere sem o numero ter mudado.
        """
        raiz = self.montar(**NO_LIMIAR)
        primeiro = raiz / "um.json"
        segundo = raiz / "dois.json"
        for destino in (primeiro, segundo):
            with contextlib.redirect_stdout(io.StringIO()):
                principal(["--root", str(raiz), "--json", str(destino), "medir"])
        self.assertEqual(primeiro.read_bytes(), segundo.read_bytes())

    def test_o_nucleo_tambem_escreve_artefacto(self) -> None:
        raiz = self.montar(**NO_LIMIAR)
        destino = raiz / "nucleo.json"
        with contextlib.redirect_stdout(io.StringIO()):
            codigo = principal(
                ["--root", str(raiz), "--json", str(destino), "nucleo"]
            )
        self.assertEqual(codigo, 0)
        mapa = json.loads(destino.read_text(encoding="utf-8"))
        self.assertEqual(mapa["fluxo"], 0)
        self.assertTrue(mapa["passa"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
