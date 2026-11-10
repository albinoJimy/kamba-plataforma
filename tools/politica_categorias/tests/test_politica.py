"""A politica de categorias como *policy-as-code* (KAM-088).

`TestRepositorio` e o que poe a politica no gate 4: a fonte do repositorio
cumpre o esquema, a versao esta fixada no lock e o modulo TypeScript gerado
corresponde a fonte. Alterar a politica sem passar por aqui avermelha o gate.

Os outros casos correm numa **arvore temporaria** com a politica real copiada:
um ensaio que escrevesse em `policy/` deixava o repositorio alterado quando
falhasse a meio.
"""

from __future__ import annotations

import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from politica_categorias import cli, esquema
from politica_categorias import politica as pol

RAIZ = Path(__file__).resolve().parents[3]


def correr(raiz: Path, comando: str) -> tuple[int, str, str]:
    saida, erro = io.StringIO(), io.StringIO()
    with redirect_stdout(saida), redirect_stderr(erro):
        codigo = cli.main([comando, "--root", str(raiz)])
    return codigo, saida.getvalue(), erro.getvalue()


class TestRepositorio(unittest.TestCase):
    def test_a_politica_do_repositorio_esta_conforme(self) -> None:
        codigo, saida, erro = correr(RAIZ, "check")
        self.assertEqual(codigo, 0, erro)
        self.assertIn("conforme", saida)

    def test_as_oito_do_piloto_sao_bloqueada_e_as_cinco_permitidas(self) -> None:
        decisoes = {e["id"]: e["decisao"] for e in pol.ler(RAIZ).documento["categorias"]}
        for ident in (
            "armas", "jogos", "alcool", "tabaco", "medicamentos_saude",
            "clinicas", "credito_mlm_cripto", "animais_vivos_combustiveis",
        ):
            self.assertEqual(decisoes[ident], "bloqueada", ident)
        for ident in ("moda", "electronica", "servicos", "restauracao_formal", "material_construcao"):
            self.assertEqual(decisoes[ident], "permitida", ident)


class Arvore(unittest.TestCase):
    def setUp(self) -> None:
        temporaria = tempfile.TemporaryDirectory()
        self.addCleanup(temporaria.cleanup)
        self.raiz = Path(temporaria.name)
        for caminho in (pol.FONTE, pol.ESQUEMA, pol.LOCK, pol.GERADO):
            destino = self.raiz / caminho
            destino.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(RAIZ / caminho, destino)

    def fonte(self) -> str:
        return (self.raiz / pol.FONTE).read_text(encoding="utf-8")

    def escrever(self, texto: str) -> None:
        (self.raiz / pol.FONTE).write_text(texto, encoding="utf-8", newline="")


class TestVersao(Arvore):
    def test_mudar_o_conteudo_sem_subir_a_versao_reprova(self) -> None:
        self.escrever(self.fonte().replace("      - tequila\n", "", 1))
        codigo, _, erro = correr(self.raiz, "check")
        self.assertEqual(codigo, 1)
        self.assertIn("mudou sem a versao subir", erro)
        codigo, _, erro = correr(self.raiz, "gerar")
        self.assertEqual(codigo, 2)
        self.assertIn("sobe a `versao`", erro)

    def test_subir_a_versao_fixa_a_nova_e_o_check_passa(self) -> None:
        self.escrever(
            self.fonte().replace("      - tequila\n", "", 1).replace('versao: "1.0.0"', 'versao: "1.1.0"', 1)
        )
        self.assertEqual(correr(self.raiz, "check")[0], 1)
        self.assertEqual(correr(self.raiz, "gerar")[0], 0)
        self.assertEqual(correr(self.raiz, "check")[0], 0)
        lock = pol.ler_lock(self.raiz)
        self.assertEqual([v for v, _ in lock], ["1.0.0", "1.1.0"])

    def test_descer_a_versao_reprova(self) -> None:
        self.escrever(self.fonte().replace("      - tequila\n", "", 1).replace('versao: "1.0.0"', 'versao: "0.9.0"', 1))
        self.assertEqual(correr(self.raiz, "gerar")[0], 2)

    def test_um_gerado_desactualizado_reprova(self) -> None:
        caminho = self.raiz / pol.GERADO
        caminho.write_text(caminho.read_text(encoding="utf-8") + "// editado\n", encoding="utf-8")
        codigo, _, erro = correr(self.raiz, "check")
        self.assertEqual(codigo, 1)
        self.assertIn("nao corresponde a fonte", erro)


class TestInvariantes(Arvore):
    def assertInvalida(self, texto: str, mensagem: str) -> None:
        self.escrever(texto)
        codigo, _, erro = correr(self.raiz, "check")
        self.assertEqual(codigo, 2, erro)
        self.assertIn(mensagem, erro)

    def test_fonte_lei_sem_parecer(self) -> None:
        self.assertInvalida(self.fonte().replace(" (a confirmar por parecer)", "", 1), "sem '(a confirmar por parecer)'")

    def test_decisao_fora_do_dominio(self) -> None:
        self.assertInvalida(self.fonte().replace("decisao: bloqueada", "decisao: proibida", 1), "fora de")

    def test_chave_nao_prevista(self) -> None:
        self.assertInvalida(
            self.fonte().replace("    decisao: bloqueada\n", "    decisao: bloqueada\n    excepcoes: []\n", 1),
            "chave nao prevista 'excepcoes'",
        )

    def test_estado_de_evidencia_fora_da_escala(self) -> None:
        self.assertInvalida(self.fonte().replace("estado_evidencia: CONFIRMADO", "estado_evidencia: PROVAVEL", 1), "fora de")

    def test_termo_repetido_entre_entradas(self) -> None:
        self.assertInvalida(self.fonte().replace("      - tequila\n", "      - tequila\n      - moda\n", 1), "termo 'moda'")

    def test_padrao_invalido(self) -> None:
        self.assertInvalida(self.fonte().replace("    padroes: []\n", "    padroes:\n      - '(sem fecho'\n", 1), "invalido")

    def test_versao_que_nao_e_semver(self) -> None:
        self.assertInvalida(self.fonte().replace('versao: "1.0.0"', 'versao: "1.0"', 1), "nao casa")

    def test_bloqueada_sem_fonte(self) -> None:
        texto = self.fonte().replace(
            'fonte_meta: "E1 §4 (CONFIRMADO): drogas com receita ou recreativas"', "fonte_meta: null", 1
        )
        self.assertInvalida(texto, "drogas: bloqueada sem fonte_meta nem fonte_lei")


class TestValidador(unittest.TestCase):
    def test_recusa_palavra_chave_que_nao_implementa(self) -> None:
        with self.assertRaises(esquema.EsquemaInvalido):
            esquema.erros({}, {"type": "object", "oneOf": []})
        with self.assertRaises(esquema.EsquemaInvalido):
            esquema.erros({}, {"type": "object", "additionalProperties": True})

    def test_o_esquema_do_repositorio_so_usa_o_que_esta_implementado(self) -> None:
        documento = json.loads((RAIZ / pol.ESQUEMA).read_text(encoding="utf-8"))
        self.assertEqual(esquema.erros({"versao": "1.0.0", "categorias": []}, documento), ["$.categorias: menos de 1 itens"])

    def test_tipos_e_unicidade(self) -> None:
        self.assertEqual(esquema.erros(True, {"type": "integer"}), ["$: tipo bool, esperado integer"])
        self.assertEqual(esquema.erros(["a", "a"], {"type": "array", "uniqueItems": True}), ["$: item repetido 'a'"])
        self.assertEqual(esquema.erros(None, {"type": ["string", "null"], "minLength": 1}), [])


if __name__ == "__main__":
    unittest.main()
