"""O gate 9: o canario e detectado, e o que nao e segredo nao e achado.

O teste central e o do canario, e e o que o ticket exige: «um segredo-canario
(formato de chave de API) numa *fixture* de teste falha o PR; o mesmo segredo
fora das areas permitidas falha sempre».
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scan_secrets.patterns import CLASSES, PADROES, entropia_de_shannon
from scan_secrets.scanner import (
    ConfiguracaoInvalida,
    Permissoes,
    varrer_ficheiros,
    varrer_texto,
)

ROOT = Path(__file__).resolve().parents[3]
CANARIO = Path(__file__).resolve().parent / "fixtures" / "canario"


class TestCanario(unittest.TestCase):
    """O canario prova que o scanner funciona. Sem ele, o gate 9 e uma promessa."""

    def setUp(self) -> None:
        self.permissoes = Permissoes.ler(ROOT)

    def test_o_canario_existe(self) -> None:
        self.assertTrue((CANARIO / "segredos.txt").is_file())
        self.assertTrue((CANARIO / "chave_privada.txt").is_file())

    def test_na_sua_pasta_e_permitido(self) -> None:
        achados = varrer_ficheiros(
            [CANARIO / "segredos.txt", CANARIO / "chave_privada.txt"],
            ROOT,
            self.permissoes,
        )
        self.assertEqual(
            achados,
            [],
            "a area do canario esta declarada em ci/secrets-allow.yaml:\n"
            + "\n".join(str(a) for a in achados),
        )

    def test_fora_da_pasta_e_detectado(self) -> None:
        """O mesmo conteudo, noutro caminho, falha sempre."""
        texto = (CANARIO / "segredos.txt").read_text(encoding="utf-8")
        achados = varrer_texto(texto, "services/gwy/src/config.ts", self.permissoes)
        self.assertGreaterEqual(
            len(achados), 9, "cada linha do canario tem de bater num padrao"
        )

    def test_cada_padrao_de_chave_tem_um_caso_no_canario(self) -> None:
        """Se um padrao novo entrar sem caso, o canario deixa de o cobrir."""
        texto = (CANARIO / "segredos.txt").read_text(encoding="utf-8")
        texto += (CANARIO / "chave_privada.txt").read_text(encoding="utf-8")
        sem_caso = [
            padrao.nome
            for padrao in PADROES
            if not padrao.expressao.search(texto)
        ]
        self.assertEqual(
            sem_caso,
            [],
            f"padroes sem caso no canario: {sem_caso} — acrescente um valor de "
            "forma real a tools/scan_secrets/tests/fixtures/canario/",
        )

    def test_a_amostra_nao_revela_o_segredo(self) -> None:
        """Um relatorio que imprime o segredo copia-o para os logs do CI."""
        texto = (CANARIO / "segredos.txt").read_text(encoding="utf-8")
        achados = varrer_texto(texto, "qualquer/sitio.ts", self.permissoes)
        self.assertTrue(achados)
        for achado in achados:
            with self.subTest(padrao=achado.padrao):
                # Nenhuma amostra pode conter um trecho longo do valor original.
                self.assertLessEqual(len(achado.amostra.split("…")[0]), 6)
                self.assertIn("…", achado.amostra + "…")


class TestFalsosPositivos(unittest.TestCase):
    """O que tem forma de segredo e nao e. Cada um deixaria o gate vermelho por nada."""

    def setUp(self) -> None:
        self.permissoes = Permissoes.ler(ROOT)

    def nao_acha(self, texto: str, ficheiro: str = "qualquer/sitio.ts") -> None:
        achados = varrer_texto(texto, ficheiro, self.permissoes)
        self.assertEqual(achados, [], "\n".join(str(a) for a in achados))

    def test_sha_de_commit_nao_e_segredo(self) -> None:
        """Um digest e publico por desenho. Flagou 11 ficheiros do KAM-001."""
        self.nao_acha('commit: "0123456789abcdef0123456789abcdef01234567"')

    def test_integrity_do_npm_nao_e_segredo(self) -> None:
        self.nao_acha("integrity: sha512-JaUWUqGWeFr18ovabf6NxYLr76SsHRgCIc4TkCMcX7dmN4Iu")

    def test_hash_do_pip_nao_e_segredo(self) -> None:
        self.nao_acha(
            "    --hash=sha256:6152fdbbf9a77fdec97731721bebf7c4c44f7c29b424b0065826173efc7ed101"
        )

    def test_digest_de_imagem_nao_e_segredo(self) -> None:
        self.nao_acha(
            "image: pgvector/pgvector@sha256:2358fcba361ed2233a5ed81b5fe4ca779ccb304120ce531a3bf51c0ed7e2bc11"
        )

    def test_placeholder_nao_e_segredo(self) -> None:
        for valor in ("mude-me-localmente", "SEU-SEGREDO-AQUI", "changeme", "placeholder"):
            with self.subTest(valor=valor):
                self.nao_acha(f"POSTGRES_PASSWORD={valor}")

    def test_palavra_de_baixa_entropia_nao_e_segredo(self) -> None:
        """`password = "aaaaaaaaaaaaaaaa"` nao e um segredo; e um teste mal feito."""
        self.nao_acha('password = "aaaaaaaaaaaaaaaaaa"')

    def test_o_env_example_do_repositorio_esta_limpo(self) -> None:
        achados = varrer_ficheiros([ROOT / ".env.example"], ROOT, self.permissoes)
        self.assertEqual(achados, [], "\n".join(str(a) for a in achados))


def _casos_nomeados() -> dict[str, str]:
    """Casos positivos, lidos da pasta do canario.

    Nao estao em linha neste ficheiro de proposito: o gate 9 recusou o commit
    deste proprio modulo quando os tinha, e tinha razao. O criterio de aceitacao
    diz que "um segredo-canario numa fixture de teste falha o PR" — uma fixture
    nao e passe livre. A unica area declarada em `ci/secrets-allow.yaml` e a
    pasta do canario, e e la que os valores vivem.
    """
    casos: dict[str, str] = {}
    for linha in (CANARIO / "casos.txt").read_text(encoding="utf-8").splitlines():
        if not linha.strip() or linha.startswith("#") or "|" not in linha:
            continue
        nome, _, conteudo = linha.partition("|")
        casos[nome.strip()] = conteudo
    return casos


class TestVerdadeirosPositivos(unittest.TestCase):
    def setUp(self) -> None:
        self.permissoes = Permissoes.ler(ROOT)
        self.casos = _casos_nomeados()

    def acha(self, nome_do_caso: str, padrao_esperado: str) -> None:
        texto = self.casos[nome_do_caso]
        achados = varrer_texto(texto, "services/gwy/src/x.ts", self.permissoes)
        nomes = [a.padrao for a in achados]
        self.assertIn(padrao_esperado, nomes, f"achados: {nomes}")

    def test_atribuicao_com_entropia(self) -> None:
        self.acha("atribuicao", "atribuicao")

    def test_credencial_em_url(self) -> None:
        self.acha("credencial_em_url", "credencial_em_url")

    def test_chave_privada(self) -> None:
        self.acha("chave_privada", "chave_privada")

    def test_token_da_meta(self) -> None:
        """O token que da acesso ao WABA do cliente (E1)."""
        self.acha("meta_token_longo", "meta_token_longo")

    def test_chave_da_openai(self) -> None:
        self.acha("openai", "openai")

    def test_todos_os_casos_nomeados_batem(self) -> None:
        """Nenhum caso do ficheiro fica sem ser exercitado."""
        for nome, texto in self.casos.items():
            with self.subTest(caso=nome):
                achados = varrer_texto(texto, "services/gwy/src/x.ts", self.permissoes)
                self.assertTrue(achados, f"o caso {nome!r} nao bateu em nada")


class TestEntropia(unittest.TestCase):
    def test_texto_tem_entropia_baixa(self) -> None:
        self.assertLess(entropia_de_shannon("aaaaaaaaaaaa"), 1.0)

    def test_chave_tem_entropia_alta(self) -> None:
        self.assertGreater(entropia_de_shannon("K7mQ2vXn4pL9wR3tY6uI8oA1sD5f"), 4.0)


class TestConfiguracao(unittest.TestCase):
    def test_sem_ficheiro_levanta(self) -> None:
        """Sem permissoes, tudo seria achado: o gate falharia por configuracao."""
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ConfiguracaoInvalida):
                Permissoes.ler(Path(tmp))

    def test_area_sem_razao_e_recusada(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            (raiz / "ci").mkdir()
            (raiz / "ci" / "secrets-allow.yaml").write_text(
                "version: 1\nareas:\n  - caminho: x\n    classes:\n      - chave_api\n",
                encoding="utf-8",
            )
            with self.assertRaises(ConfiguracaoInvalida):
                Permissoes.ler(raiz)

    def test_as_classes_declaradas_existem_nos_padroes(self) -> None:
        """Uma classe inventada na configuracao nao dispensa nada.

        Aconteceu duas vezes. A primeira, a area do canario dizia
        `classes: [canario]`, que nenhum padrao produz, e o canario era
        flagueado na sua propria pasta.

        A segunda foi deste teste. A versao anterior comparava contra
        `reais | {"placeholders", "exemplos", "digests"}` — e `placeholders` e
        `exemplos` nao sao classes de padrao nenhum. O conjunto foi alargado
        para o teste passar, e com isso o teste passou a abencoar exactamente
        os nomes inoperantes que existia para apanhar: tres das quatro areas
        declaravam-nos, nao permitiam nada, e nada o dizia. Compara-se contra
        `CLASSES` e mais nada.
        """
        from kamba_yaml import load_file

        dados = load_file(ROOT / "ci" / "secrets-allow.yaml")
        for area in dados["areas"]:
            for classe in area["classes"]:
                with self.subTest(area=area["caminho"], classe=classe):
                    self.assertIn(
                        classe,
                        CLASSES,
                        f"a classe {classe!r} nao e produzida por nenhum padrao",
                    )

    def test_classe_inventada_e_recusada_na_leitura(self) -> None:
        """A recusa esta na leitura, e nao so num teste sobre o ficheiro real."""
        with tempfile.TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            (raiz / "ci").mkdir()
            (raiz / "ci" / "secrets-allow.yaml").write_text(
                "version: 1\n"
                "placeholders_literais:\n"
                "  - changeme\n"
                "areas:\n"
                "  - caminho: docs/**\n"
                "    classes:\n"
                "      - exemplos\n"
                "    razao: >-\n"
                "      Uma razao com mais de trinta caracteres, para passar a outra regra.\n",
                encoding="utf-8",
                newline="\n",
            )
            with self.assertRaises(ConfiguracaoInvalida) as capturado:
                Permissoes.ler(raiz)
        self.assertIn("exemplos", str(capturado.exception))


class TestEvasoesFechadas(unittest.TestCase):
    """Formas de passar por baixo do gate 9 que passavam, e ja nao passam.

    Cada um destes casos foi encontrado a tentar evadir o gate, nao a ler o
    codigo. Sao a parte do ficheiro que mais vale manter viva.
    """

    def setUp(self) -> None:
        self.permissoes = Permissoes.ler(ROOT)
        self.casos = _casos_nomeados()

    def test_variavel_de_ambiente_com_prefixo(self) -> None:
        """`POSTGRES_PASSWORD=` e a forma mais comum de segredo que existe.

        A fronteira de palavra nao casa dentro de um identificador, porque `_`
        e caractere de palavra. Enquanto o padrao a usou, nem
        `POSTGRES_PASSWORD=`, nem `META_ACCESS_TOKEN=`, nem
        `AWS_SECRET_ACCESS_KEY=` batiam em nada — e o `.env.example` deste
        repositorio usa a primeira forma.
        """
        for nome in (
            "atribuicao_com_prefixo",
            "atribuicao_meta",
            "atribuicao_aws",
            "atribuicao_sufixo",
        ):
            with self.subTest(caso=nome):
                achados = varrer_texto(self.casos[nome], "x.ts", self.permissoes)
                self.assertTrue(achados, f"{nome} passou sem ser visto")

    def test_linha_longa_e_varrida_em_janelas(self) -> None:
        """Acrescentar espacos era a evasao mais barata que havia.

        A linha com mais de 4096 caracteres era saltada, com um comentario a
        dizer que isso "se dizia" — e nao se dizia nada.
        """
        from scan_secrets.scanner import LIMITE_DE_LINHA

        segredo = self.casos["openai"]
        linha = "// " + ("x" * (LIMITE_DE_LINHA + 500)) + " " + segredo
        achados = varrer_texto(linha, "x.ts", self.permissoes)
        self.assertTrue(achados, "segredo depois de 4596 caracteres passou")

    def test_o_segredo_na_fronteira_de_duas_janelas_e_visto(self) -> None:
        """A sobreposicao existe para isto: um valor partido ao meio."""
        from scan_secrets.scanner import LIMITE_DE_LINHA, SOBREPOSICAO

        segredo = self.casos["openai"]
        self.assertLess(
            len(segredo), SOBREPOSICAO, "a sobreposicao tem de cobrir o maior caso"
        )
        # Coloca-se o segredo a cavalo da primeira fronteira de janela.
        enchimento = "x" * (LIMITE_DE_LINHA - len(segredo) // 2)
        achados = varrer_texto(enchimento + segredo + "y" * 100, "x.ts", self.permissoes)
        self.assertTrue(achados, "segredo na fronteira das janelas passou")

    def test_o_mesmo_segredo_nao_se_reporta_duas_vezes(self) -> None:
        """As janelas sobrepoem-se; o relatorio nao duplica."""
        from scan_secrets.scanner import LIMITE_DE_LINHA

        segredo = self.casos["openai"]
        enchimento = "x" * (LIMITE_DE_LINHA - len(segredo) // 2)
        achados = varrer_texto(enchimento + segredo, "x.ts", self.permissoes)
        self.assertEqual(len(achados), 1, [str(a) for a in achados])

    def test_palavra_dispensada_dentro_do_valor_nao_dispensa(self) -> None:
        """`...-redacted` dispensava qualquer valor que a contivesse.

        A comparacao era por contencao e nao por igualdade, pelo que sete
        substrings de uso corrente desligavam o scanner. `unknown` era a pior:
        entrou por causa de `KAMBA_COMMIT_SHA=unknown`.
        """
        achados = varrer_texto(
            self.casos["atribuicao_com_palavra_dispensada"], "x.ts", self.permissoes
        )
        self.assertTrue(achados, "valor terminado em `-redacted` passou")

    def test_chave_com_prefixo_nao_consulta_os_placeholders(self) -> None:
        """Para `chave_api` o prefixo e a prova, e nenhuma palavra o anula."""
        achados = varrer_texto(
            self.casos["chave_api_com_palavra_dispensada"], "x.ts", self.permissoes
        )
        self.assertTrue(achados, "chave `sk-proj-...redacted` passou")

    def test_o_placeholder_exacto_continua_a_dispensar(self) -> None:
        """A correccao nao pode tornar o `.env.example` vermelho."""
        self.assertTrue(self.permissoes.e_placeholder("mude-me-localmente"))
        self.assertTrue(self.permissoes.e_placeholder('"SEU-SEGREDO-AQUI"'))
        self.assertFalse(self.permissoes.e_placeholder("Qh7vK2mZr9TpXw4Ln8Bs-example"))


class TestRepositorio(unittest.TestCase):
    def test_a_arvore_seguida_pelo_git_esta_limpa(self) -> None:
        from scan_secrets.cli import ficheiros_seguidos

        permissoes = Permissoes.ler(ROOT)
        achados = varrer_ficheiros(ficheiros_seguidos(ROOT), ROOT, permissoes)
        self.assertEqual(achados, [], "\n".join(str(a) for a in achados))


if __name__ == "__main__":
    unittest.main()
