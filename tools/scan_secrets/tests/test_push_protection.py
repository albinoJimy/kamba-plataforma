"""O `.github/secret_scanning.yml` nao pode divergir do `ci/secrets-allow.yaml`.

**Porque isto e um teste e nao uma nota no README.** A via A do KAM-157 pede ao
GitHub que deixe de olhar para uma pasta. Isso so e aceitavel enquanto essa
pasta for **exactamente** a que o repositorio ja declarou como a unica area onde
um valor com forma de segredo e permitido — e as duas listas vivem em ficheiros
diferentes, mantidos por pessoas diferentes, em momentos diferentes.

Divergirem em silencio e o unico modo de falha serio desta via: bastava
acrescentar um caminho ao `paths-ignore` para criar uma area cega que ninguem
reviu. Este teste e o que o impede.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from kamba_yaml import load_file

ROOT = Path(__file__).resolve().parents[3]
PERMITIDAS = ROOT / "ci" / "secrets-allow.yaml"
IGNORADAS = ROOT / ".github" / "secret_scanning.yml"

#: A area do canario, escrita aqui tambem. Nao e redundancia: e o terceiro
#: ponto que torna um erro de copia visivel. Com dois, uma alteracao em ambos
#: passa; com tres, tem de se enganar em todos.
AREA_DO_CANARIO = "tools/scan_secrets/tests/fixtures/canario/**"


class TestAsDuasListasCoincidem(unittest.TestCase):
    def setUp(self) -> None:
        self.assertTrue(IGNORADAS.is_file(), f"{IGNORADAS} nao existe")
        self.ignoradas = load_file(IGNORADAS)
        self.permitidas = load_file(PERMITIDAS)

    def caminhos_permitidos(self) -> set[str]:
        return {str(a["caminho"]) for a in self.permitidas.get("areas") or []}

    def test_o_ficheiro_so_tem_a_chave_que_o_github_le(self) -> None:
        """Uma chave a mais aqui e politica que ninguem aplica — e o GitHub nao
        avisa que a ignorou. E a mesma postura do KAM-134 sobre `ci/*.yaml`."""
        self.assertEqual(set(self.ignoradas), {"paths-ignore"})

    def test_ignora_exactamente_uma_area(self) -> None:
        """**Uma**, e nao «as do canario mais aquela outra».

        O argumento inteiro da via A e nao acrescentar excepcao nenhuma: alinhar
        o scanner do GitHub com uma que ja estava declarada. Um caminho a mais
        destroi esse argumento, e destroi-o em silencio.
        """
        self.assertEqual(self.ignoradas["paths-ignore"], [AREA_DO_CANARIO])

    def test_a_area_ignorada_esta_declarada_em_secrets_allow(self) -> None:
        for caminho in self.ignoradas["paths-ignore"]:
            with self.subTest(caminho=caminho):
                self.assertIn(
                    caminho,
                    self.caminhos_permitidos(),
                    "o `paths-ignore` esconde do GitHub um caminho que o "
                    "`ci/secrets-allow.yaml` nao declara. Ou se declara la, com "
                    "razao escrita, ou sai daqui.",
                )

    def test_a_area_do_canario_continua_declarada(self) -> None:
        """O inverso: se a entrada do canario sair do `ci/secrets-allow.yaml`, o
        `paths-ignore` fica a apontar para o nada — e o gate 9 passa a ficar
        vermelho sobre o canario, que e o que se quer, mas com o scanner do
        GitHub cego na mesma."""
        self.assertIn(AREA_DO_CANARIO, self.caminhos_permitidos())

    def test_a_pasta_existe_e_tem_canarios(self) -> None:
        pasta = ROOT / "tools" / "scan_secrets" / "tests" / "fixtures" / "canario"
        self.assertTrue(pasta.is_dir())
        ficheiros = [f for f in pasta.iterdir() if f.suffix != ".md"]
        self.assertGreaterEqual(
            len(ficheiros), 1,
            "um `paths-ignore` sobre uma pasta sem canarios e uma area cega sem "
            "razao de ser",
        )


class TestOGateContinuaAVer(unittest.TestCase):
    """«Qualquer via que torne o canario invisivel ao scanner do repositorio nao
    pode torna-lo invisivel ao scanner do gate» — criterio 5 do KAM-157.

    Sao dois scanners, e este ficheiro so fala com um deles.
    """

    def test_o_nosso_scanner_nao_le_o_secret_scanning_yml(self) -> None:
        """A prova mais directa: o `paths-ignore` nao existe no nosso codigo.

        Se um dia alguem o fizer ler este ficheiro «para serem coerentes», a
        prova de que o gate 9 morde desaparece no mesmo *commit* — e e por isso
        que a assercao e sobre o codigo e nao sobre o comportamento.
        """
        fontes = (ROOT / "tools" / "scan_secrets").rglob("*.py")
        for fonte in fontes:
            if "tests" in fonte.parts:
                continue
            with self.subTest(ficheiro=fonte.name):
                texto = fonte.read_text(encoding="utf-8")
                self.assertNotIn("secret_scanning", texto)
                self.assertNotIn("paths-ignore", texto)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
