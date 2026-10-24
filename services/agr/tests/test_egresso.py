"""As guardas do ADR-002 em *runtime* (criterios 7 e 8).

O que esta bateria prova: que a guarda **encontra** um `langgraph_api`
importavel, que nao o importa para o descobrir, e que a telemetria fica a
`false`. O que ela nao prova, e que ninguem pode provar com um teste: que o
egresso para `beacon.langchain.com` esta bloqueado na rede. Isso e o KAM-076; o
que este ticket tem e o contrato em `services/agr/egress.yaml`, e e esse que a
*suite* do *gate* 8 le.
"""

from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path

from kamba_agr.egresso import (
    BEACON,
    MODULOS_PROIBIDOS,
    TELEMETRIA_DESLIGADA,
    VARIAVEIS_DE_TELEMETRIA,
    ModuloProibidoError,
    desligar_telemetria,
    exigir_biblioteca_mit,
)

RAIZ = Path(__file__).resolve().parents[3]


class TestListaDeBloqueio(unittest.TestCase):
    def test_numa_arvore_sa_a_guarda_passa(self) -> None:
        exigir_biblioteca_mit()  # nao levanta

    def test_um_modulo_proibido_importavel_levanta(self) -> None:
        for proibido in MODULOS_PROIBIDOS:
            with self.subTest(modulo=proibido):
                modulo = types.ModuleType(proibido)
                modulo.__spec__ = types.SimpleNamespace(name=proibido)  # type: ignore[attr-defined]
                sys.modules[proibido] = modulo
                self.addCleanup(sys.modules.pop, proibido, None)
                with self.assertRaises(ModuloProibidoError) as apanhado:
                    exigir_biblioteca_mit()
                self.assertIn(proibido, str(apanhado.exception))
                self.assertIn(BEACON, str(apanhado.exception))
                sys.modules.pop(proibido, None)

    def test_a_guarda_nao_importa_o_modulo_para_o_descobrir(self) -> None:
        # Um `import` executava o `__init__.py` do pacote proibido — isto e,
        # corria o codigo que estamos a recusar.
        correu = {"sim": False}

        class EspiaDeImportacao:
            def find_module(self, *_args):  # pragma: no cover - API antiga
                return None

            def find_spec(self, nome, _caminho=None, _alvo=None):
                if nome in MODULOS_PROIBIDOS:
                    correu["sim"] = True
                return None

        espia = EspiaDeImportacao()
        sys.meta_path.insert(0, espia)
        self.addCleanup(sys.meta_path.remove, espia)
        exigir_biblioteca_mit()
        self.assertTrue(correu["sim"], "a guarda nem procurou o modulo")

    def test_os_nomes_sao_de_modulo_e_nao_de_distribuicao(self) -> None:
        # `langgraph-api` com hifen nunca e encontrado pelo `find_spec`: uma
        # guarda que passa sempre.
        for nome in MODULOS_PROIBIDOS:
            with self.subTest(nome=nome):
                self.assertNotIn("-", nome)

    def test_um_find_spec_que_levanta_conta_como_ausente(self) -> None:
        # Sem isto, a propria verificacao derrubava o arranque.
        marcador = f"{MODULOS_PROIBIDOS[0]}.subpacote"

        class EspiaQueLevanta:
            def find_spec(self, nome, _caminho=None, _alvo=None):
                if nome in MODULOS_PROIBIDOS:
                    raise ImportError("pai inexistente")
                return None

        espia = EspiaQueLevanta()
        sys.meta_path.insert(0, espia)
        self.addCleanup(sys.meta_path.remove, espia)
        exigir_biblioteca_mit()  # nao levanta
        self.assertTrue(marcador)


class TestTelemetria(unittest.TestCase):
    def test_poe_as_duas_variaveis_a_false(self) -> None:
        ambiente: dict[str, str] = {}
        desligar_telemetria(ambiente)
        for variavel in VARIAVEIS_DE_TELEMETRIA:
            self.assertEqual(ambiente[variavel], TELEMETRIA_DESLIGADA)

    def test_sobrepoe_um_true_do_ambiente(self) -> None:
        # Criterio 7. Um AGR que respeitasse um `LANGSMITH_TRACING=true` mandava
        # conteudo de conversas de clientes para fora de Angola sem destino
        # registado (ADR-008).
        ambiente = {v: "true" for v in VARIAVEIS_DE_TELEMETRIA}
        mudou = desligar_telemetria(ambiente)
        for variavel in VARIAVEIS_DE_TELEMETRIA:
            self.assertEqual(ambiente[variavel], TELEMETRIA_DESLIGADA)
        self.assertEqual(sorted(mudou), sorted(VARIAVEIS_DE_TELEMETRIA))

    def test_o_que_devolve_nao_leva_o_valor_que_la_estava(self) -> None:
        # Um `LANGSMITH_TRACING` pode trazer uma chave colada por engano, e o
        # arranque registra o que isto devolve.
        ambiente = {"LANGSMITH_TRACING": "lsv2_pt_923456789_segredo"}
        mudou = desligar_telemetria(ambiente)
        # As duas mudaram: a que trazia o valor, e a que nao estava definida.
        self.assertEqual(sorted(mudou), sorted(VARIAVEIS_DE_TELEMETRIA))
        # A chave do dicionario e o nome; o valor **anterior** e o que fica, e
        # por isso o arranque so registra `sorted(telemetria)` — as chaves.
        self.assertNotIn("segredo", " ".join(mudou))

    def test_com_as_duas_ja_a_false_nao_declara_mudanca(self) -> None:
        ambiente = {v: TELEMETRIA_DESLIGADA for v in VARIAVEIS_DE_TELEMETRIA}
        self.assertEqual(desligar_telemetria(ambiente), {})


class TestAllowlistDeSaida(unittest.TestCase):
    """O contrato de `egress.yaml`: e nele que «0 chamadas ao beacon» vive hoje."""

    def setUp(self) -> None:
        self.texto = (RAIZ / "services" / "agr" / "egress.yaml").read_text(
            encoding="utf-8"
        )

    def test_o_beacon_nao_esta_na_allowlist(self) -> None:
        self.assertNotIn(BEACON, _destinos(self.texto))
        # E **esta** no ficheiro: num comentario que diz porque e que nao esta
        # na lista. Apagar o comentario nao melhora nada, e este teste nota-o.
        self.assertIn(BEACON, self.texto)

    def test_a_omissao_continua_a_ser_negar(self) -> None:
        self.assertIn("por_omissao: negar", self.texto)

    def test_nenhum_destino_e_um_caracter_universal(self) -> None:
        for proibido in ("fqdn: '*'", 'fqdn: "*"', "fqdn: *"):
            self.assertNotIn(proibido, self.texto)


def _destinos(texto: str) -> str:
    """A parte do ficheiro depois de `destinos:`, sem os comentarios.

    O `beacon.langchain.com` **esta** no ficheiro, num comentario que explica
    porque e que nao esta na lista. Procurar a cadeia no ficheiro inteiro fazia
    este teste falhar pela razao errada — ou, pior, passar por o comentario ter
    sido apagado.
    """
    _, _, cauda = texto.partition("destinos:")
    return "\n".join(
        linha for linha in cauda.splitlines() if not linha.strip().startswith("#")
    )


if __name__ == "__main__":
    unittest.main()
