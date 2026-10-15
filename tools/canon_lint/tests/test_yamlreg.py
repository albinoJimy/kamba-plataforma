"""KAM-148 — o `yamlreg` nao le mal em silencio.

Tres coisas, e as tres contam:

1. **o corpus**: cada construcao com o resultado declarado (ler a estrutura X,
   ou recusar). O corpus vive em `corpus_yamlreg.py`, porque a varredura do
   ticket usa o mesmo;
2. **a equivalencia**: a estrutura lida de cada ficheiro real, campo a campo,
   igual antes e depois — contra a copia congelada do leitor anterior
   (`leitor_antes_do_kam148.py`), e nao contra um retrato em JSON, que
   envelheceria a cada edicao de um ficheiro;
3. **o oraculo**: a copia congelada **ainda tem** os defeitos que este ticket
   fecha. Sem isto, a equivalencia passaria a verde por construcao no dia em
   que alguem «arrumasse» a copia.
"""

from __future__ import annotations

import contextlib
import io
import re
import unittest
from pathlib import Path

from canon_lint.yamlreg import YamlIlegivel, ler

from . import leitor_antes_do_kam148 as antes
from .corpus_yamlreg import (
    _FUNDO_DE_BLOCO,
    CASOS,
    DEFEITOS_DO_LEITOR_ANTERIOR,
    RECUSA,
)

RAIZ = Path(__file__).resolve().parents[3]

#: Os ficheiros que este leitor le. O `registry/` esta **reservado** pelo
#: KAM-001 e o conteudo e do EPIC-03: hoje nao tem nenhum ficheiro de producao,
#: e o corpus real sao as *fixtures* da superficie 3 do gate 3b. Isto esta dito
#: aqui, e nao escondido, porque zero ficheiros dariam zero divergencias — e o
#: criterio de aceitacao ficaria satisfeito pela razao errada.
def _corpus_real() -> tuple[list[Path], list[Path]]:
    producao = sorted(RAIZ.glob("registry/*.yaml"))
    fixtures = sorted(
        caminho
        for caminho in (RAIZ / "tools/canon_lint/tests/fixtures").rglob("*.yaml")
        # O `manifesto.yaml` e o manifesto do canario, lido pelo `kamba_yaml`.
        if caminho.name != "manifesto.yaml"
    )
    return producao, fixtures


#: O documento que fixa a forma dos manifestos, e a seccao que a mostra.
DESENHO = RAIZ / "docs/tecnica/02_Agent_Runtime_Verticais.md"


def _manifestos_documentados() -> list[str]:
    """Os manifestos de `docs/tecnica/02` §5.1, extraidos do proprio documento.

    Enquanto `registry/` nao tiver ficheiros de producao, estes sao o corpus
    mais parecido com eles que existe: a forma que o EPIC-03 vai escrever, com
    estilo de fluxo nas `subscriptions`, nos `models`, nos `guardrails` e no
    `golden`. Leem-se do documento e nao de uma copia, para que uma alteracao do
    desenho chegue aqui sem ninguem se lembrar de a copiar.
    """
    texto = DESENHO.read_text(encoding="utf-8")
    seccao = texto[texto.index("### 5.1") : texto.index("### 5.2")]
    return re.findall(r"```yaml\n(.*?)```", seccao, re.S)


def _folhas(no, prefixo: str = "") -> dict[str, object]:
    """Cada escalar da estrutura, com o caminho em que esta.

    Um contentor **vazio** tambem e uma folha, com uma marca propria: sem isso,
    `[]`, `{}` e a chave ausente eram indistinguiveis, e os 18 `[]` do
    `ops/secrets-inventory.yaml` ficavam fora da equivalencia — uma chave de
    valor `[]` a desaparecer passava a verde, que e precisamente «uma entrada do
    inventario que desaparece».
    """
    if isinstance(no, dict):
        if not no:
            return {prefixo: "<mapa vazio>"}
        folhas: dict[str, object] = {}
        for chave, valor in no.items():
            folhas.update(_folhas(valor, f"{prefixo}.{chave}"))
        return folhas
    if isinstance(no, list):
        if not no:
            return {prefixo: "<lista vazia>"}
        folhas = {}
        for indice, valor in enumerate(no):
            folhas.update(_folhas(valor, f"{prefixo}[{indice}]"))
        return folhas
    return {prefixo: no}


class TestCorpusDaVarredura(unittest.TestCase):
    """Cada construcao da varredura, com o resultado que o ticket lhe decidiu."""

    def test_cada_caso_tem_o_resultado_declarado(self) -> None:
        for nome, (texto, esperado) in CASOS.items():
            with self.subTest(caso=nome):
                if esperado is RECUSA:
                    with self.assertRaises(YamlIlegivel, msg=f"devia recusar: {nome}"):
                        ler(texto)
                else:
                    self.assertEqual(ler(texto), esperado, msg=nome)

    def test_o_corpus_cobre_as_quatro_classes(self) -> None:
        """Um corpus so de recusas, ou so de leituras, nao e uma varredura."""
        recusas = sum(1 for _, esperado in CASOS.values() if esperado is RECUSA)
        self.assertGreater(recusas, 50)
        self.assertGreater(len(CASOS) - recusas, 30)

    def test_a_mensagem_da_recusa_diz_a_linha(self) -> None:
        with self.assertRaises(YamlIlegivel) as capturado:
            ler("a: 1\nb: 2\nc: 1.5\n")
        self.assertIn("linha 3", str(capturado.exception))

    def test_a_mensagem_nomeia_a_construcao(self) -> None:
        for texto, agulha in (
            ("activo: FALSE\n", "ambiguo"),
            ("limiar: 0x1f\n", "parece um numero"),
            ('tom: "abre\n', "aberta e nao fechada"),
            ("l:\n  - - a\n", "lista aninhada"),
            ("a:\n  <<: valor\n", "merge key"),
            ("a: [1,, 2]\n", "valor vazio"),
            ("a: { : 1 }\n", "chave vazia"),
            # A mensagem do indicador em **posicao de chave**: sem estas linhas, a
            # recusa nomeada podia desaparecer e o caso continuava a recusar —
            # pela mensagem generica. Foi uma mutacao sobrevivente que o mostrou.
            ("@a: 1\n", "indicador reservado"),
            ("%YAML 1.2\n", "directiva"),
            (_FUNDO_DE_BLOCO, "niveis de aninhamento"),
        ):
            with self.subTest(texto=texto):
                with self.assertRaises(YamlIlegivel) as capturado:
                    ler(texto)
                self.assertIn(agulha, str(capturado.exception))


class TestFicheirosReais(unittest.TestCase):
    """O corpus real le-se, e sabe-se qual e."""

    def test_todos_os_ficheiros_reais_se_leem(self) -> None:
        """O corpus descobre-se por *glob*: no dia em que o EPIC-03 escrever o
        primeiro `registry/*.yaml`, ele entra aqui e na equivalencia sem se
        alterar uma linha. Nao se fixa a lista — nem se exige que `registry/`
        continue vazio, que seria fazer falhar o ticket que o preencher."""
        producao, fixtures = _corpus_real()
        self.assertGreaterEqual(len(fixtures), 4, "as fixtures da superficie 3 desapareceram")
        for caminho in producao + fixtures:
            with self.subTest(ficheiro=caminho.name):
                documento = ler(caminho.read_text(encoding="utf-8"))
                self.assertIsInstance(documento, dict)

    def test_os_manifestos_documentados_leem_se(self) -> None:
        """A forma que o EPIC-03 vai escrever (`docs/tecnica/02` §5.1) le-se com
        as recusas novas. Enquanto `registry/` estiver vazio, e esta a prova de
        que nenhuma delas recusa **de mais** sobre o corpus que vem a seguir."""
        documentados = _manifestos_documentados()
        self.assertEqual(len(documentados), 2, "o §5.1 deixou de ter os dois manifestos")
        for indice, texto in enumerate(documentados, 1):
            with self.subTest(manifesto=indice):
                documento = ler(texto)
                self.assertIsInstance(documento, dict)
                # As chaves de topo sao as que o `registo.py` fecha.
                self.assertIn("subscriptions", documento)
                self.assertIn("entitlements", documento)
                self.assertEqual(documento["subscriptions"][0]["versao"], 1)

    def test_nenhuma_recusa_nova_apanha_um_ficheiro_real(self) -> None:
        """As recusas novas foram escolhidas depois de se confirmar que nenhum
        ficheiro real as dispara. Se um ficheiro novo as disparar, e aqui que
        se ve, e a resposta e aspas ou uma regra nova com teste."""
        producao, fixtures = _corpus_real()
        for caminho in producao + fixtures:
            texto = caminho.read_text(encoding="utf-8")
            with self.subTest(ficheiro=caminho.name):
                ler(texto)


class TestEquivalenciaAntesEDepois(unittest.TestCase):
    """A estrutura lida de cada ficheiro real, campo a campo, antes e depois."""

    def test_cada_ficheiro_real_le_igual(self) -> None:
        producao, fixtures = _corpus_real()
        documentados = _manifestos_documentados()
        fontes = [(c.name, c.read_text(encoding="utf-8")) for c in producao + fixtures]
        fontes += [(f"{DESENHO.name} §5.1 [{i}]", t) for i, t in enumerate(documentados, 1)]
        self.assertTrue(fontes, "sem ficheiros nao ha equivalencia que medir")
        divergencias: list[str] = []
        campos = 0
        for nome, texto in fontes:
            antigas = _folhas(antes.ler(texto))
            novas = _folhas(ler(texto))
            campos += len(antigas)
            for caminho_do_campo in sorted(set(antigas) | set(novas)):
                velho = antigas.get(caminho_do_campo, "<ausente>")
                novo = novas.get(caminho_do_campo, "<ausente>")
                if velho != novo:
                    divergencias.append(f"{nome}{caminho_do_campo}: {velho!r} -> {novo!r}")
        self.assertEqual(
            divergencias,
            [],
            f"a leitura de um ficheiro real mudou de resultado ({campos} campos folha "
            f"em {len(fontes)} fonte(s): {len(producao)} de producao, "
            f"{len(fixtures)} fixtures, {len(documentados)} manifestos documentados)",
        )
        self.assertGreater(campos, 20, "corpus demasiado pequeno para a prova valer")

    def test_o_leitor_congelado_ainda_tem_os_defeitos(self) -> None:
        """Se a copia congelada perder os defeitos, deixou de ser oraculo."""
        for nome, (texto, estrutura_errada) in DEFEITOS_DO_LEITOR_ANTERIOR.items():
            with self.subTest(defeito=nome):
                self.assertEqual(antes.ler(texto), estrutura_errada, msg=nome)
                # E o leitor de hoje nao a devolve.
                try:
                    hoje = ler(texto)
                except YamlIlegivel:
                    continue
                self.assertNotEqual(hoje, estrutura_errada, msg=nome)


class TestRecusaChegaAQuemChama(unittest.TestCase):
    """Uma recusa do leitor **bloqueia** o gate 3b, e nomeia o ficheiro.

    O KAM-136 pediu codigo **2** para uma recusa, porque os `ci/*.yaml` sao a
    configuracao do proprio *gate*: «nao consigo verificar» nao e «encontrei
    achados». Aqui a escolha e outra, e esta escrita no ticket: um
    `registry/*.yaml` e o **objecto** que o *gate* 3b analisa, nao a sua
    configuracao. Por isso a recusa chega como `Achado(ILEGIVEL)` — codigo 1,
    com o caminho do ficheiro — e e isso que `tools/canon_lint/registo.py`
    declara desde o KAM-111: «um ficheiro que este leitor nao percebe **falha**
    o gate: nao passa por nao ter sido lido». O que nao e aceitavel, e nao
    acontece, e uma recusa que nao bloqueia nada.
    """

    def test_um_registry_ilegivel_e_um_achado_que_nomeia_o_ficheiro(self) -> None:
        from canon_lint import registo
        from canon_lint.achados import ILEGIVEL

        from .base import saber

        achados = registo.verificar("registry/mau.yaml", "id: FALSE\n", saber())
        self.assertEqual(len(achados), 1)
        self.assertEqual(achados[0].classe, ILEGIVEL)
        self.assertEqual(achados[0].ficheiro, "registry/mau.yaml")
        self.assertIn("ambiguo", achados[0].mensagem)

    def test_o_cli_devolve_um_e_nao_um_traceback(self) -> None:
        import tempfile

        from canon_lint.cli import main

        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "mau.yaml"
            caminho.write_text("id: FALSE\n", encoding="utf-8")
            self.assertEqual(
                main(["--root", str(RAIZ), "ficheiro", "registo", str(caminho)]), 1
            )

    def test_um_ficheiro_que_nao_e_utf8_e_erro_de_configuracao(self) -> None:
        """Nao e `OSError`: sem a linha do KAM-148, o `ficheiro` morria com
        *traceback* e codigo 1 em vez de dizer que nao consegue ler."""
        import tempfile

        from canon_lint.cli import main

        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "latin1.yaml"
            caminho.write_bytes(b"id: vendedor\nnota: caf\xe9\n")
            capturado = io.StringIO()
            with contextlib.redirect_stderr(capturado):
                codigo = main(["--root", str(RAIZ), "ficheiro", "registo", str(caminho)])
        self.assertEqual(codigo, 2)
        # E a mensagem nomeia o ficheiro, que a do `UnicodeDecodeError` nao faz.
        self.assertIn("latin1.yaml", capturado.getvalue())


class TestNenhumaExcepcaoEscapa(unittest.TestCase):
    """A unica excepcao que sai deste leitor e a dele.

    Uma construcao que o faca rebentar com um `TypeError`, um `IndexError` ou um
    `RecursionError` nao e uma recusa: e um *gate* morto com *traceback* e
    codigo 1, que foi o que o KAM-136 encontrou no `kamba_yaml` com um ficheiro
    que nao era UTF-8. A prova e por mutacao de um caractere sobre os ficheiros
    reais e sobre todo o corpus, com semente fixa para nao ter dias bons.
    """

    SIGNIFICATIVOS = list("\n\r\t -:#\"'[]{},&*!|>%@`~.\\0127abz\u0085\u2028\ufeff\x00")

    def _muta(self, rng, texto: str) -> str:
        if not texto:
            return rng.choice(self.SIGNIFICATIVOS)
        indice = rng.randrange(len(texto))
        modo = rng.choice(("insere", "apaga", "troca"))
        if modo == "insere":
            return texto[:indice] + rng.choice(self.SIGNIFICATIVOS) + texto[indice:]
        if modo == "apaga":
            return texto[:indice] + texto[indice + 1 :]
        return texto[:indice] + rng.choice(self.SIGNIFICATIVOS) + texto[indice + 1 :]

    def test_dez_mil_mutacoes_nao_produzem_outra_excepcao(self) -> None:
        import random

        producao, fixtures = _corpus_real()
        sementes = [caminho.read_text(encoding="utf-8") for caminho in producao + fixtures]
        sementes += [texto for texto, _ in CASOS.values()]
        rng = random.Random(144)
        for _ in range(10_000):
            texto = rng.choice(sementes)
            for _ in range(rng.randrange(1, 4)):
                texto = self._muta(rng, texto)
            try:
                ler(texto)
            except YamlIlegivel:
                continue
            except Exception as erro:  # noqa: BLE001
                self.fail(f"{type(erro).__name__} em vez de recusa, com {texto!r}: {erro}")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
