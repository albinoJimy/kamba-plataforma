"""O leitor de YAML aceita a forma do inventario e recusa o resto (KAM-010).

O **KAM-148** acrescentou as tres ultimas classes: o corpus da varredura (cada
construcao com o resultado declarado), a equivalencia campo a campo contra a
copia congelada do leitor anterior, e a prova de que essa copia **ainda tem**
os defeitos que o ticket fecha — sem a qual a equivalencia passaria a verde
por construcao no dia em que alguem a «arrumasse».
"""

from __future__ import annotations

import unittest
from pathlib import Path

from secrets_inventory.yamlsubset import YamlSubsetError, load

from . import leitor_antes_do_kam148 as antes
from .corpus_yamlsubset import CASOS, DEFEITOS_DO_LEITOR_ANTERIOR, RECUSA

RAIZ = Path(__file__).resolve().parents[3]
INVENTARIO = RAIZ / "ops/secrets-inventory.yaml"


class TestAceita(unittest.TestCase):
    def test_escalares(self) -> None:
        lido = load(
            "\n".join(
                [
                    "versao: 1",
                    "ticket: KAM-010",
                    'fonte: "docs/tecnica/08 §5"',
                    "activo: true",
                    "inactivo: false",
                    "sem_valor: null",
                    "til: ~",
                ]
            )
        )
        self.assertEqual(lido["versao"], 1)
        self.assertEqual(lido["ticket"], "KAM-010")
        self.assertEqual(lido["fonte"], "docs/tecnica/08 §5")
        self.assertIs(lido["activo"], True)
        self.assertIs(lido["inactivo"], False)
        self.assertIsNone(lido["sem_valor"])
        self.assertIsNone(lido["til"])

    def test_valor_entre_aspas_mantem_dois_pontos(self) -> None:
        # Metade das notas do inventario tem dois pontos no meio.
        lido = load('nota: "le-o o processo de migracao: nunca a aplicacao"')
        self.assertEqual(lido["nota"], "le-o o processo de migracao: nunca a aplicacao")

    def test_valor_entre_aspas_mantem_o_cardinal(self) -> None:
        lido = load('nota: "chave #1 do facilitador"')
        self.assertEqual(lido["nota"], "chave #1 do facilitador")

    def test_comentarios_e_linhas_vazias(self) -> None:
        lido = load("# comentario\n\nversao: 1  # no fim da linha\n  # indentado\n")
        self.assertEqual(lido, {"versao": 1})

    def test_listas_de_fluxo(self) -> None:
        lido = load("ambientes: [dev, staging, prod]\nvazia: []")
        self.assertEqual(lido["ambientes"], ["dev", "staging", "prod"])
        self.assertEqual(lido["vazia"], [])

    def test_lista_de_mapas(self) -> None:
        lido = load(
            "\n".join(
                [
                    "segredos:",
                    "  - id: meta_app_secret",
                    "    ambientes: [dev, prod]",
                    "    anel: true",
                    "  - id: pepper_contact_hmac",
                    "    ambientes: [prod]",
                    "    anel: false",
                ]
            )
        )
        self.assertEqual(
            lido["segredos"],
            [
                {"id": "meta_app_secret", "ambientes": ["dev", "prod"], "anel": True},
                {"id": "pepper_contact_hmac", "ambientes": ["prod"], "anel": False},
            ],
        )

    def test_o_inventario_a_serio_le_se(self) -> None:
        from pathlib import Path

        raiz = Path(__file__).resolve().parents[3]
        lido = load((raiz / "ops" / "secrets-inventory.yaml").read_text(encoding="utf-8"))
        self.assertEqual(lido["versao"], 1)
        self.assertIsInstance(lido["segredos"], list)
        self.assertGreater(len(lido["segredos"]), 10)


class TestRecusa(unittest.TestCase):
    def _recusa(self, texto: str) -> str:
        with self.assertRaises(YamlSubsetError) as capturado:
            load(texto)
        return str(capturado.exception)

    def test_tabulacao(self) -> None:
        self.assertIn("tabulacao", self._recusa("a:\n\t- b: 1"))

    def test_sem_dois_pontos(self) -> None:
        self.assertIn("chave: valor", self._recusa("so texto"))

    def test_item_de_lista_sem_chave_de_lista(self) -> None:
        self.assertIn("sem chave de lista", self._recusa("  - id: x"))

    def test_item_de_lista_sem_par(self) -> None:
        self.assertIn("chave: valor", self._recusa("lista:\n  - so_texto"))

    def test_lista_de_fluxo_sem_fecho(self) -> None:
        self.assertIn("sem fecho", self._recusa("ambientes: [dev, prod"))

    def test_lista_de_listas(self) -> None:
        self.assertIn("lista de listas", self._recusa("a: [[1], [2]]"))

    def test_lista_aninhada(self) -> None:
        self.assertIn("aninhada", self._recusa("a:\n  - b: 1\n    c:\n"))

    def test_chave_repetida_no_item(self) -> None:
        self.assertIn("repetida", self._recusa("a:\n  - id: x\n    id: y"))

    def test_indentacao_de_item_inconsistente(self) -> None:
        self.assertIn("item inconsistente", self._recusa("a:\n  - id: x\n    - id: y"))

    def test_indentacao_de_chave_inconsistente(self) -> None:
        self.assertIn("chave inconsistente", self._recusa("a:\n  - id: x\n        owner: y"))

    def test_ancora_e_escalar_de_bloco(self) -> None:
        for texto in ("a: &ancora x", "a: |", "a: >", "a: !tipo"):
            with self.subTest(texto=texto):
                self._recusa(texto)

    def test_chave_indentada_fora_de_item(self) -> None:
        self.assertIn("fora de um item", self._recusa("a: 1\n  b: 2"))


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
                    with self.assertRaises(YamlSubsetError, msg=f"devia recusar: {nome}"):
                        load(texto)
                else:
                    self.assertEqual(load(texto), esperado, msg=nome)

    def test_o_corpus_cobre_as_duas_saidas(self) -> None:
        """Um corpus so de recusas, ou so de leituras, nao e uma varredura."""
        recusas = sum(1 for _, esperado in CASOS.values() if esperado is RECUSA)
        self.assertGreater(recusas, 40)
        self.assertGreater(len(CASOS) - recusas, 20)

    def test_a_mensagem_da_recusa_diz_a_linha(self) -> None:
        with self.assertRaises(YamlSubsetError) as capturado:
            load("a: 1\nb: 2\nc: 1.5\n")
        self.assertIn("linha 3", str(capturado.exception))

    def test_a_mensagem_nomeia_a_construcao(self) -> None:
        for texto, agulha in (
            ("obrigatorio: FALSE\n", "ambiguo"),
            ("rotacao_dias: 0180\n", "parece um numero"),
            ('nota: "abre\n', "aberta e nao fechada"),
            ("id: 1\nid: 2\n", "chave repetida no mapa de topo"),
            ("ambientes: [dev,, prod]\n", "valor vazio"),
            ('ambientes: ["dev, prod]\n', "aberta e nao fechada"),
            ("@a: 1\n", "indicador reservado"),
            ("%YAML 1.2\n", "directiva"),
            ("<<: a\n", "merge key"),
        ):
            with self.subTest(texto=texto):
                with self.assertRaises(YamlSubsetError) as capturado:
                    load(texto)
                self.assertIn(agulha, str(capturado.exception))


class TestEquivalenciaAntesEDepois(unittest.TestCase):
    """A estrutura lida do inventario real, campo a campo, antes e depois.

    O corpus deste leitor e **um** ficheiro — `ops/secrets-inventory.yaml` — e
    esta dito aqui para que o criterio nao fique satisfeito pela razao errada:
    zero ficheiros dariam zero divergencias.
    """

    def test_o_inventario_real_le_igual(self) -> None:
        self.assertTrue(INVENTARIO.is_file(), f"{INVENTARIO} desapareceu")
        texto = INVENTARIO.read_text(encoding="utf-8")
        antigas = _folhas(antes.load(texto))
        novas = _folhas(load(texto))
        divergencias = [
            f"{caminho}: {antigas.get(caminho, '<ausente>')!r} -> {novas.get(caminho, '<ausente>')!r}"
            for caminho in sorted(set(antigas) | set(novas))
            if antigas.get(caminho, "<ausente>") != novas.get(caminho, "<ausente>")
        ]
        self.assertEqual(
            divergencias,
            [],
            f"a leitura do inventario mudou de resultado ({len(antigas)} campos folha)",
        )
        self.assertGreater(len(antigas), 300, "corpus demasiado pequeno para a prova valer")

    def test_o_leitor_congelado_ainda_tem_os_defeitos(self) -> None:
        """Se a copia congelada perder os defeitos, deixou de ser oraculo."""
        for nome, (texto, estrutura_errada) in DEFEITOS_DO_LEITOR_ANTERIOR.items():
            with self.subTest(defeito=nome):
                self.assertEqual(antes.load(texto), estrutura_errada, msg=nome)
                try:
                    hoje = load(texto)
                except YamlSubsetError:
                    continue
                self.assertNotEqual(hoje, estrutura_errada, msg=nome)


class TestNenhumaExcepcaoEscapa(unittest.TestCase):
    """A unica excepcao que sai deste leitor e a dele.

    Uma construcao que o faca rebentar com um `TypeError`, um `IndexError` ou um
    `RecursionError` nao e uma recusa: e uma *suite* morta com *traceback*, que
    foi o que o KAM-136 encontrou no `kamba_yaml` com um ficheiro que nao era
    UTF-8. A prova e por mutacao de um caractere sobre o inventario real e sobre
    todo o corpus, com semente fixa para nao ter dias bons.
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

        sementes = [INVENTARIO.read_text(encoding="utf-8")]
        sementes += [texto for texto, _ in CASOS.values()]
        rng = random.Random(144)
        for _ in range(10_000):
            texto = rng.choice(sementes)
            for _ in range(rng.randrange(1, 4)):
                texto = self._muta(rng, texto)
            try:
                load(texto)
            except YamlSubsetError:
                continue
            except Exception as erro:  # noqa: BLE001
                self.fail(f"{type(erro).__name__} em vez de recusa, com {texto!r}: {erro}")


class TestRecusaChegaAQuemChama(unittest.TestCase):
    """Uma recusa do leitor **bloqueia**, e nomeia o ficheiro e a linha.

    O KAM-136 pedia codigo 2 porque os `ci/*.yaml` sao a configuracao do
    proprio *gate*. Aqui a forma e outra, e esta escrita no ticket: o inventario
    nao e configuracao de um *gate*, e o que o verifica e uma *suite* de testes
    (`TestInventarioReal.test_esquema_valido`, que exige `erros == []`). Uma
    recusa do leitor chega por essa lista — nao por excepcao, nao em silencio —
    e **falha o teste**, com o caminho do ficheiro e a linha na mensagem.
    """

    def test_carregar_devolve_a_recusa_na_lista_de_erros(self) -> None:
        import tempfile

        from secrets_inventory.inventario import carregar

        with tempfile.TemporaryDirectory() as pasta:
            raiz = Path(pasta)
            (raiz / "ops").mkdir()
            (raiz / "ops" / "secrets-inventory.yaml").write_text(
                "versao: 1\nid: 1\nid: 2\n", encoding="utf-8"
            )
            inventario, erros = carregar(raiz)
        self.assertEqual(len(erros), 1, erros)
        # O `CAMINHO_INVENTARIO` sai com o separador do sistema operativo.
        self.assertIn("secrets-inventory.yaml", erros[0].replace("\\", "/"))
        self.assertIn("linha 3", erros[0])
        self.assertIn("chave repetida no mapa de topo", erros[0])
        self.assertEqual(inventario.segredos, ())


if __name__ == "__main__":
    unittest.main()
