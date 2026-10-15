"""`kamba_core.logger`: a *allowlist*, as formas e as recusas (KAM-068).

Tres camadas, por ordem de quem manda:

1. **Os vectores de paridade** (`packages/core-ts/tests/fixtures/logger_paridade.json`)
   — a mesma tabela que `packages/core-ts/tests/logger.test.ts` le. E ela que
   diz o que as duas linguagens tem de aceitar e recusar.
2. **Os canarios** — telefone, NIF, e-mail, texto, token, IBAN e referencia,
   por todas as portas de uma chamada. Nenhum pode aparecer na saida.
3. **O que e so de Python** — argumentos por nome que colidem com parametros,
   objectos com `__str__` armadilhado, o modo estrito.

A ponte para o `logging` da biblioteca padrao esta em `test_logger_ponte.py`.
Este modulo esta no estrato `critico` de `ci/thresholds.yaml` (90%).
"""

from __future__ import annotations

import datetime
import io
import json
import os
import unittest
import uuid
from pathlib import Path
from unittest import mock

from kamba_core import logger
from kamba_core.logger import (
    CAMPOS,
    CAMPOS_DE_CHAMADA,
    CAMPOS_RESERVADOS,
    CONTADORES,
    METRICA_ESCRITA_FALHADA,
    METRICA_REJEITADOS,
    MOTIVOS,
    NIVEIS,
    VARIAVEL_ESTRITO,
    CampoRejeitado,
    Logger,
    ServicoInvalido,
    id_opaco,
    mascarar_referencia,
    politica,
)

ROOT = Path(__file__).resolve().parents[3]
VECTORES = json.loads(
    (ROOT / "packages" / "core-ts" / "tests" / "fixtures" / "logger_paridade.json").read_text(
        encoding="utf-8"
    )
)

PARADO = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
TENANT = "0b6f1d2e-3c4a-4b5c-8d6e-7f8091a2b3c4"

#: Canarios: nenhum pode aparecer na saida, por nenhum caminho. Todos inventados.
#: O token e montado por partes para nao ter, no repositorio, a forma de um.
CANARIOS = {
    "telefone_internacional": "+244 923 456 789",
    "telefone_colado": "+244923456789",
    "telefone_sem_mais": "244 923 456 789",
    "telefone_nacional": "923456789",
    "telefone_com_pontos": "923.456.789",
    "telefone_com_hifenes": "923-456-789",
    "nif_colectivo": "5417123456",
    "nif_singular": "004567890LA045",
    "email": "joaquina.canario@exemplo.co.ao",
    "texto": "Bom dia, queria encomendar duas pizzas para o Kilamba",
    "transcricao": "mana, manda o comprovativo que o mano ja transferiu",
    "nome": "Joaquina Canario dos Santos",
    "morada": "Rua do Canario 12, Bairro Operario, Luanda",
    "token": "EAA" + "x9" * 30,
    "portador": "Bearer " + "tk" + "9z" * 14,
    "iban": "AO06004000001234567890123",
    "iban_espacado": "AO06 0040 0000 1234 5678 9012 3",
    "referencia": "00123 456 789 012",
    "provider_event_id": "evt_" + "3kQ9xZ2mP7aLw8Tn5VbR1cYd",
    "wamid": "wamid.HBgMMjQ0OTIzNDU2Nzg5FQIAEhgUM0FCQ0RFRjAxMjM0NTY3ODlBQkMA",
}


def _novo(estrito: bool = False, svc: str = "paridade") -> tuple[Logger, io.StringIO]:
    saida = io.StringIO()
    return Logger(svc, destino=saida, relogio=lambda: PARADO, estrito=estrito), saida


def _linhas(saida: io.StringIO) -> list[dict]:
    return [json.loads(linha) for linha in saida.getvalue().splitlines()]


def _rejeicoes() -> dict[str, int]:
    prefixo = METRICA_REJEITADOS + ":"
    return {
        nome[len(prefixo) :]: valor
        for nome, valor in CONTADORES.ler().items()
        if nome.startswith(prefixo)
    }


class _ErroComClasse:
    """Constroi uma excepcao cuja classe tem o nome dado (como o condutor do X-11)."""

    @staticmethod
    def criar(classe: str, mensagem: str) -> Exception:
        return type(classe, (Exception,), {})(mensagem)


class TestPolitica(unittest.TestCase):
    """A lista e exactamente a de `docs/tecnica/08` §7.3."""

    def test_a_allowlist_e_exactamente_a_do_documento(self) -> None:
        self.assertEqual(
            CAMPOS,
            (
                "ts", "level", "svc", "tenant_id", "contact_hmac_prefix", "turn_id",
                "msg_id", "wa_type", "latency_ms", "tool", "outcome", "error_code",
            ),
        )
        self.assertEqual(len(CAMPOS), 12)
        self.assertEqual(len(set(CAMPOS)), 12)

    def test_a_allowlist_e_a_que_esta_escrita_no_documento_tecnico(self) -> None:
        """Lida do §7.3, para que mudar um dos dois sem o outro falhe aqui."""
        texto = (ROOT / "docs" / "tecnica" / "08_Seguranca_Conformidade.md").read_text(
            encoding="utf-8"
        )
        inicio = texto.index("### 7.3 Logs sem conteúdo")
        marcador = "*allowlist* de campos: `"
        lista = texto.index(marcador, inicio) + len(marcador)
        do_documento = tuple(c.strip() for c in texto[lista : texto.index("`", lista)].split(","))
        self.assertEqual(CAMPOS, do_documento)

    def test_os_vectores_dizem_a_mesma_politica(self) -> None:
        self.assertEqual(list(CAMPOS), VECTORES["campos"])
        self.assertEqual(list(CAMPOS_RESERVADOS), VECTORES["campos_reservados"])
        self.assertEqual(list(NIVEIS), VECTORES["niveis"])
        self.assertEqual(list(MOTIVOS), VECTORES["motivos"])
        self.assertEqual(METRICA_REJEITADOS, VECTORES["metrica_rejeitados"])
        self.assertEqual(METRICA_ESCRITA_FALHADA, VECTORES["metrica_escrita_falhada"])
        self.assertEqual(VARIAVEL_ESTRITO, VECTORES["variavel_estrito"])

    def test_reservados_e_de_chamada_partem_a_lista_em_dois(self) -> None:
        self.assertEqual(CAMPOS_RESERVADOS + CAMPOS_DE_CHAMADA, CAMPOS)

    def test_nao_ha_campo_de_conteudo(self) -> None:
        """Texto, transcricao, telefone, morada e nome nao existem como campos."""
        proibidos = {
            "texto", "text", "mensagem", "message", "msg", "body", "transcricao",
            "transcript", "telefone", "phone", "msisdn", "morada", "address", "nome",
            "name", "display_name", "email", "nif", "bsuid", "contact_id",
            "referencia", "provider_event_id", "headers",
        }
        self.assertEqual(proibidos & set(CAMPOS), set())


class TestVectoresDeParidade(unittest.TestCase):
    def setUp(self) -> None:
        CONTADORES.repor()

    def test_validar_campo_a_campo(self) -> None:
        self.assertGreaterEqual(len(VECTORES["validar"]), 100)
        for caso in VECTORES["validar"]:
            with self.subTest(campo=caso["campo"], valor=repr(caso["valor"])):
                self.assertEqual(politica.validar(caso["campo"], caso["valor"]), caso["saida"])

    def test_nomes_de_servico(self) -> None:
        for caso in VECTORES["svc"]:
            with self.subTest(valor=repr(caso["valor"])):
                aceite = politica.validar_svc(caso["valor"]) is not None
                self.assertEqual(aceite, caso["aceite"])
                if caso["aceite"]:
                    self.assertEqual(Logger(caso["valor"], destino=io.StringIO()).svc, caso["valor"])
                else:
                    with self.assertRaises(ServicoInvalido):
                        Logger(caso["valor"], destino=io.StringIO())

    def test_casos_linha_a_linha(self) -> None:
        self.assertGreaterEqual(len(VECTORES["casos"]), 15)
        for caso in VECTORES["casos"]:
            with self.subTest(caso=caso["nome"]):
                CONTADORES.repor()
                registo, saida = _novo()
                erro = caso.get("erro")
                if erro is not None:
                    registo.excepcao(
                        _ErroComClasse.criar(erro["classe"], erro["mensagem"]),
                        caso["codigo"],
                        **caso["campos"],
                    )
                else:
                    registo.registar(caso["nivel"], caso["posicionais"], caso["campos"])
                self.assertEqual(saida.getvalue(), caso["linha"] + "\n")
                self.assertEqual(_rejeicoes(), caso["rejeicoes"])

    def test_id_opaco(self) -> None:
        for caso in VECTORES["id_opaco"]:
            with self.subTest(entrada=caso["entrada"]):
                self.assertEqual(id_opaco(caso["entrada"]), caso["saida"])
                self.assertEqual(politica.validar("msg_id", caso["saida"]), caso["saida"])

    def test_mascarar_referencia(self) -> None:
        for caso in VECTORES["mascarar_referencia"]:
            with self.subTest(entrada=repr(caso["entrada"])):
                self.assertEqual(mascarar_referencia(caso["entrada"]), caso["saida"])


class TestLinha(unittest.TestCase):
    def setUp(self) -> None:
        CONTADORES.repor()

    def test_uma_linha_json_por_chamada_com_os_campos_pela_ordem_da_lista(self) -> None:
        registo, saida = _novo()
        registo.info(outcome="ok", tenant_id=TENANT, latency_ms=3)
        registo.warn(tool="criar_pedido")
        texto = saida.getvalue()
        self.assertEqual(texto.count("\n"), 2)
        primeira = json.loads(texto.splitlines()[0])
        self.assertEqual(list(primeira), ["ts", "level", "svc", "tenant_id", "latency_ms", "outcome"])
        self.assertEqual(primeira["svc"], "paridade")

    def test_os_quatro_niveis(self) -> None:
        registo, saida = _novo()
        registo.debug(outcome="ok")
        registo.info(outcome="ok")
        registo.warn(outcome="ok")
        registo.error(outcome="ok")
        self.assertEqual([linha["level"] for linha in _linhas(saida)], list(NIVEIS))

    def test_o_ts_e_utc_com_milissegundos_e_z(self) -> None:
        luanda = datetime.timezone(datetime.timedelta(hours=1))
        instante = datetime.datetime(2026, 10, 12, 9, 30, 15, 123999, tzinfo=luanda)
        saida = io.StringIO()
        Logger("gwy", destino=saida, relogio=lambda: instante).info()
        self.assertEqual(_linhas(saida)[0]["ts"], "2026-10-12T08:30:15.123Z")

    def test_o_relogio_por_omissao_e_o_de_agora_em_utc(self) -> None:
        saida = io.StringIO()
        antes = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=1)
        Logger("gwy", destino=saida).info()
        ts = datetime.datetime.fromisoformat(_linhas(saida)[0]["ts"].replace("Z", "+00:00"))
        self.assertGreaterEqual(ts, antes.replace(microsecond=0))
        self.assertLess(ts, antes + datetime.timedelta(seconds=30))

    def test_o_destino_por_omissao_e_o_stdout_do_momento(self) -> None:
        captura = io.StringIO()
        registo = Logger("gwy", relogio=lambda: PARADO)
        with mock.patch("sys.stdout", captura):
            registo.info(outcome="ok")
        self.assertEqual(json.loads(captura.getvalue())["outcome"], "ok")

    def test_tenant_como_uuid_tem_de_vir_em_texto(self) -> None:
        """So texto: e o que `tenant_guard.normalizar_tenant` devolve."""
        registo, saida = _novo()
        registo.info(tenant_id=uuid.UUID(TENANT))
        self.assertNotIn("tenant_id", _linhas(saida)[0])
        self.assertEqual(_rejeicoes(), {"valor_invalido": 1})


class TestCanarios(unittest.TestCase):
    """Nenhum canario aparece na saida, entre por onde entrar."""

    def setUp(self) -> None:
        CONTADORES.repor()

    def _sem_canarios(self, saida: io.StringIO) -> None:
        texto = saida.getvalue()
        for nome, canario in CANARIOS.items():
            self.assertNotIn(canario, texto, nome)
        # Nem os digitos soltos de um dos telefones, do NIF ou do IBAN.
        for digitos in ("923456789", "5417123456", "004567890", "0040000012345"):
            self.assertNotIn(digitos, texto)

    def test_em_cada_campo_da_allowlist(self) -> None:
        registo, saida = _novo()
        for campo in CAMPOS_DE_CHAMADA:
            for canario in CANARIOS.values():
                registo.info(**{campo: canario, "outcome" if campo != "outcome" else "tool": "ok"})
        self._sem_canarios(saida)
        esperadas = len(CAMPOS_DE_CHAMADA) * len(CANARIOS)
        self.assertEqual(len(_linhas(saida)), esperadas)
        self.assertEqual(_rejeicoes(), {"valor_invalido": esperadas})

    def test_em_campos_que_nao_existem(self) -> None:
        registo, saida = _novo()
        for campo in ("telefone", "nome", "morada", "texto", "transcricao", "email", "nif",
                      "iban", "referencia", "provider_event_id", "extra", "contexto", "message"):
            for canario in CANARIOS.values():
                registo.info(**{campo: canario})
        self._sem_canarios(saida)
        self.assertEqual(set(_rejeicoes()), {"campo_desconhecido"})

    def test_como_nome_do_campo(self) -> None:
        registo, saida = _novo()
        for canario in CANARIOS.values():
            registo.info(**{canario: "ok", "outcome": "ok"})
        self._sem_canarios(saida)
        self.assertEqual(_rejeicoes(), {"campo_desconhecido": len(CANARIOS)})

    def test_aninhado_em_dicionarios_e_listas_a_qualquer_profundidade(self) -> None:
        registo, saida = _novo()
        for canario in CANARIOS.values():
            fundo = {"a": [{"b": {"c": [canario, {"telefone": canario}]}}]}
            registo.error(tool=fundo, outcome=[canario], error_code=(canario,), contexto=fundo,
                          extra={"headers": {"Authorization": canario}}, wa_type={canario})
        self._sem_canarios(saida)
        for linha in _linhas(saida):
            self.assertEqual(set(linha), {"ts", "level", "svc"})

    def test_em_argumentos_posicionais(self) -> None:
        registo, saida = _novo()
        for canario in CANARIOS.values():
            registo.info(canario)
            registo.error("falhou para %s", canario, {"telefone": canario})
        self._sem_canarios(saida)
        self.assertEqual(_rejeicoes(), {"mensagem_livre": 4 * len(CANARIOS)})

    def test_na_mensagem_de_uma_excepcao(self) -> None:
        registo, saida = _novo()
        for canario in CANARIOS.values():
            try:
                raise ValueError(f"nao foi possivel entregar a {canario}")
            except ValueError as erro:
                registo.excepcao(erro, "entrega_falhada", tenant_id=TENANT)
        self._sem_canarios(saida)
        for linha in _linhas(saida):
            self.assertEqual(linha["error_code"], "entrega_falhada:ValueError")
            self.assertEqual(linha["level"], "error")
        self.assertEqual(_rejeicoes(), {})

    def test_em_excepcoes_encadeadas_e_com_notas(self) -> None:
        """`__cause__`, `__context__`, `args` e `add_note`: nada disso e lido."""
        registo, saida = _novo()
        for canario in CANARIOS.values():
            try:
                try:
                    raise KeyError(canario)
                except KeyError as dentro:
                    fora = RuntimeError(canario, {"telefone": canario})
                    fora.add_note(canario)
                    raise fora from dentro
            except RuntimeError as erro:
                registo.excepcao(erro, "falha_encadeada")
        self._sem_canarios(saida)
        self.assertEqual(
            {linha["error_code"] for linha in _linhas(saida)}, {"falha_encadeada:RuntimeError"}
        )

    def test_no_nome_da_classe_e_no_codigo_do_erro(self) -> None:
        registo, saida = _novo()
        for canario in CANARIOS.values():
            classe = "E" + "".join(c for c in canario if c.isalnum())
            registo.excepcao(_ErroComClasse.criar(classe, "x"), "entrega_falhada")
            registo.excepcao(ValueError("x"), canario)
            registo.excepcao(ValueError("x"), {"codigo": canario})
        texto = saida.getvalue()
        for digitos in ("923456789", "5417123456", "004567890", "0040000012345"):
            self.assertNotIn(digitos, texto)
        self._sem_canarios(saida)

    def test_cabecalhos_com_segredo_dao_zero(self) -> None:
        """`Authorization`, `X-Signature`, `Cookie` e `webhook_token`, nunca."""
        segredo = "canario" + "-de-" + "cabecalho"
        cabecalhos = {
            "Authorization": f"Bearer {segredo}",
            "authorization": f"Bearer {segredo}",
            "X-Signature": f"sha256={segredo}",
            "X-Hub-Signature-256": f"sha256={segredo}",
            "Cookie": f"sessao={segredo}",
            "Set-Cookie": f"sessao={segredo}",
            "webhook_token": segredo,
            "Content-Type": "application/json",
        }
        registo, saida = _novo()
        registo.info(**cabecalhos)
        registo.info(headers=cabecalhos, outcome="ok")
        registo.info(cabecalhos)
        registo.info(tool=cabecalhos, error_code=list(cabecalhos.values()))
        for valor in cabecalhos.values():
            registo.info(outcome=valor, error_code=valor, tool=valor, wa_type=valor)
        texto = saida.getvalue()
        self.assertEqual(texto.count(segredo), 0)
        for nome in cabecalhos:
            self.assertNotIn(nome, texto)
        self.assertNotIn("application/json", texto)

    def test_em_campos_reservados(self) -> None:
        registo, saida = _novo()
        for canario in CANARIOS.values():
            registo.info(ts=canario, level=canario, svc=canario)
        self._sem_canarios(saida)
        for linha in _linhas(saida):
            self.assertEqual(
                (linha["ts"], linha["level"], linha["svc"]),
                ("2026-01-01T00:00:00.000Z", "info", "paridade"),
            )
        self.assertEqual(_rejeicoes(), {"campo_reservado": 3 * len(CANARIOS)})

    def test_embutido_num_identificador_com_boa_cara(self) -> None:
        registo, saida = _novo()
        for embutido in ("ok_923456789", "ok_923_456_789", "erro.923.456.789", "nif_5417123456",
                         "ok_ao06004000001234567890123", "E923456789", "x923456789x"):
            registo.info(outcome=embutido, tool=embutido, wa_type=embutido, error_code=embutido)
        texto = saida.getvalue()
        for digitos in ("923456789", "923_456_789", "923.456.789", "5417123456", "0040000012345"):
            self.assertNotIn(digitos, texto)

    def test_como_nome_do_servico_a_mensagem_nao_o_repete(self) -> None:
        for canario in CANARIOS.values():
            with self.assertRaises(ServicoInvalido) as capturado:
                Logger(canario, destino=io.StringIO())
            self.assertNotIn(canario, str(capturado.exception))


class TestNuncaLevanta(unittest.TestCase):
    """Fora do modo estrito, o *logger* nao derruba quem o chama."""

    def setUp(self) -> None:
        CONTADORES.repor()

    def test_campos_com_o_nome_dos_parametros_nao_colidem(self) -> None:
        """`self`, `erro`, `codigo`, `nivel`: um dicionario espalhado pode traze-los."""
        registo, saida = _novo()
        registo.info(self="x", erro="x", codigo="x", nivel="x", posicionais="x", campos="x")
        registo.excepcao(ValueError("x"), "c", self="x", erro="x", codigo="x")
        self.assertEqual(len(_linhas(saida)), 2)
        self.assertEqual(_rejeicoes(), {"campo_desconhecido": 9})

    def test_um_valor_armadilhado_nao_e_convertido(self) -> None:
        tocado: list[str] = []

        class Armadilha:
            def __str__(self) -> str:
                tocado.append("str")
                raise RuntimeError("efeito lateral de quem chamou")

            def __repr__(self) -> str:
                tocado.append("repr")
                raise RuntimeError("efeito lateral de quem chamou")

            def __eq__(self, outro) -> bool:
                tocado.append("eq")
                raise RuntimeError("efeito lateral de quem chamou")

            __hash__ = None  # type: ignore[assignment]

        registo, saida = _novo()
        registo.info(outcome=Armadilha(), tenant_id=Armadilha(), latency_ms=Armadilha(), telefone=Armadilha())
        registo.info(Armadilha())
        registo.excepcao(Armadilha(), Armadilha())
        self.assertEqual(tocado, [])
        self.assertEqual(len(_linhas(saida)), 3)

    def test_um_destino_que_falha_conta_e_segue(self) -> None:
        class Partido:
            def write(self, _texto: str) -> None:
                raise OSError("disco cheio")

            def flush(self) -> None:  # pragma: no cover - nunca chega aqui
                raise AssertionError

        registo = Logger("gwy", destino=Partido(), relogio=lambda: PARADO)
        registo.info(outcome="ok")
        registo.error(outcome="erro")
        self.assertEqual(CONTADORES.ler(), {METRICA_ESCRITA_FALHADA: 2})

    def test_uma_chave_que_nao_e_texto(self) -> None:
        registo, saida = _novo()
        registo.registar("info", (), {5: "x", ("a", "b"): "y", "outcome": "ok"})
        self.assertEqual(_linhas(saida)[0]["outcome"], "ok")
        self.assertEqual(_rejeicoes(), {"campo_desconhecido": 2})

    def test_a_forma_dinamica_aceita_o_que_lhe_derem_sem_levantar(self) -> None:
        """`registar` e a porta sem tipos: o que la chegar mal formado e contado."""
        registo, saida = _novo()
        registo.registar("info", None, None)
        registo.registar("info", "texto 923456789", "texto 923456789")
        registo.registar("info", (), ["923456789"])
        registo.registar("info", 923456789, 923456789)
        texto = saida.getvalue()
        self.assertEqual(texto.count("\n"), 4)
        self.assertNotIn("923456789", texto)
        self.assertEqual(_rejeicoes(), {"mensagem_livre": 5})

    def test_subclasses_que_mentem_nao_passam(self) -> None:
        """Achado A4 da revisao: so `str` e `int` exactos sao validados."""

        class Parte(str):
            def partition(self, _sep):
                return ("ok", "", "")

        class Curto(str):
            def __len__(self) -> int:
                return 2

        class Pequeno(int):
            def __le__(self, _outro) -> bool:
                return True

            def __ge__(self, _outro) -> bool:
                return True

        class Nivel(str):
            def __eq__(self, _outro) -> bool:
                return True

            __hash__ = str.__hash__

        class Nome(str):
            def __format__(self, _spec) -> str:
                return "telefone=923456789"

        class NomeQueMente(Nome):
            """Diz que e igual a tudo: passava por campo reservado."""

            def __eq__(self, _outro) -> bool:
                return True

            __hash__ = str.__hash__

        class Dicio(dict):
            def items(self):
                raise RuntimeError("923456789")

        class Lista(list):
            def __iter__(self):
                raise RuntimeError("923456789")

        registo, saida = _novo()
        registo.info(error_code=Parte("923456789"), outcome=Curto("x" * 500 + "923456789"),
                     latency_ms=Pequeno(923456789), tool=Parte("pedido de 923456789"))
        # Com a forma certa e o comprimento a mentir: so o tipo exacto o trava.
        registo.info(outcome=Curto("a" * 500), tool=Curto("b" * 500))
        self.assertNotIn("aaaa", saida.getvalue())
        self.assertNotIn("bbbb", saida.getvalue())
        saida.seek(0)
        saida.truncate()
        registo.info(error_code=Parte("923456789"), outcome=Curto("x" * 500 + "923456789"),
                     latency_ms=Pequeno(923456789), tool=Parte("pedido de 923456789"))
        registo.registar(Nivel("923456789"), (), {"outcome": "ok"})
        registo.registar("info", Lista(["923456789"]), Dicio(telefone="923456789"))
        texto = saida.getvalue()
        self.assertNotIn("923456789", texto)
        self.assertEqual(
            [list(linha) for linha in _linhas(saida)],
            [["ts", "level", "svc"], ["ts", "level", "svc", "outcome"], ["ts", "level", "svc"]],
        )
        self.assertEqual([linha["level"] for linha in _linhas(saida)], ["info", "error", "info"])
        estrito, _ = _novo(estrito=True)
        with self.assertRaises(CampoRejeitado) as capturado:
            estrito.registar("info", (), {Nome("telefone"): "x"})
        self.assertNotIn("923456789", str(capturado.exception))
        self.assertIn("<nome ilegivel>", str(capturado.exception))
        with self.assertRaises(CampoRejeitado) as capturado:
            estrito.registar("info", (), {NomeQueMente("x"): "y"})
        self.assertNotIn("923456789", str(capturado.exception))
        self.assertEqual(capturado.exception.rejeicoes, (("campo_desconhecido", "<nome ilegivel>"),))

    def test_um_relogio_que_falha_ou_mente_nao_escreve_nem_levanta(self) -> None:
        """Achado A6: o `ts` nunca leva o que o relogio devolveu sem ser um instante."""

        class Instante(datetime.datetime):
            def strftime(self, _formato) -> str:
                return "923456789"

            def astimezone(self, _tz=None):
                return self

        def rebenta():
            raise RuntimeError("923456789")

        class Plausivel(Instante):
            """Devolve algo com a forma certa — so o tipo exacto o trava."""

            def strftime(self, _formato) -> str:
                return "1999-09-09T09:09:09."

        for relogio in (rebenta, lambda: None, lambda: "923456789",
                        lambda: Instante(2026, 1, 1, tzinfo=datetime.timezone.utc),
                        lambda: Plausivel(2026, 1, 1, tzinfo=datetime.timezone.utc)):
            CONTADORES.repor()
            saida = io.StringIO()
            Logger("gwy", destino=saida, relogio=relogio, estrito=True).info(outcome="ok")
            self.assertEqual(saida.getvalue(), "")
            self.assertEqual(CONTADORES.ler(), {METRICA_ESCRITA_FALHADA: 1})

    def test_excepcao_sem_codigo_nao_levanta(self) -> None:
        registo, saida = _novo(estrito=True)
        registo.excepcao(ValueError("923456789"))
        registo.excepcao(ValueError("923456789"), outcome="erro")
        self.assertEqual(
            _linhas(saida),
            [
                {"ts": "2026-01-01T00:00:00.000Z", "level": "error", "svc": "paridade"},
                {"ts": "2026-01-01T00:00:00.000Z", "level": "error", "svc": "paridade", "outcome": "erro"},
            ],
        )

    def test_cada_linha_e_despejada_no_destino(self) -> None:
        despejos: list[str] = []

        class Destino(io.StringIO):
            def flush(self) -> None:
                despejos.append(self.getvalue())

        Logger("gwy", destino=Destino(), relogio=lambda: PARADO).info(outcome="ok")
        self.assertEqual(len(despejos), 1)
        self.assertIn('"outcome":"ok"', despejos[0])

    def test_o_que_nao_e_um_dicionario_no_lugar_dos_campos_conta(self) -> None:
        """Espelho de `logger.test.ts`: um erro, um mapeamento que nao e `dict`."""
        import collections
        import types

        registo, saida = _novo()
        for campos in (
            ValueError("923456789"),
            collections.OrderedDict(outcome="ok"),
            types.MappingProxyType({"outcome": "ok"}),
            {"923456789"},
            ("outcome", "ok"),
        ):
            registo.registar("info", (), campos)
        self.assertEqual(len(_linhas(saida)), 5)
        for linha in _linhas(saida):
            self.assertEqual(set(linha), {"ts", "level", "svc"})
        self.assertEqual(_rejeicoes(), {"mensagem_livre": 5})

    def test_um_erro_que_nao_e_uma_excepcao(self) -> None:
        registo, saida = _novo()
        registo.excepcao(None, "sem_erro")
        registo.excepcao("texto 923456789", "sem_erro")
        self.assertEqual(
            [linha["error_code"] for linha in _linhas(saida)],
            ["sem_erro:NoneType", "sem_erro:str"],
        )


class TestModoEstrito(unittest.TestCase):
    """O «modo de teste» do ticket: uma rejeicao levanta."""

    def setUp(self) -> None:
        CONTADORES.repor()

    def test_campo_fora_da_lista_levanta_e_nao_escreve(self) -> None:
        registo, saida = _novo(estrito=True)
        with self.assertRaises(CampoRejeitado) as capturado:
            registo.info(telefone="923456789", outcome="ok")
        self.assertEqual(saida.getvalue(), "")
        self.assertEqual(capturado.exception.rejeicoes, (("campo_desconhecido", "telefone"),))
        self.assertEqual(CONTADORES.ler(), {})

    def test_cada_motivo_levanta(self) -> None:
        registo, saida = _novo(estrito=True)
        chamadas = {
            "campo_desconhecido": lambda: registo.info(nome="x"),
            "campo_reservado": lambda: registo.info(svc="outro"),
            "valor_invalido": lambda: registo.info(outcome="Nao E Um Identificador"),
            "mensagem_livre": lambda: registo.info("texto livre"),
        }
        self.assertEqual(set(chamadas), set(MOTIVOS))
        for motivo, chamada in chamadas.items():
            with self.subTest(motivo=motivo):
                with self.assertRaises(CampoRejeitado) as capturado:
                    chamada()
                self.assertEqual([m for m, _ in capturado.exception.rejeicoes], [motivo])
        with self.assertRaises(CampoRejeitado):
            registo.registar("verboso", (), {})
        with self.assertRaises(CampoRejeitado):
            registo.excepcao(ValueError("x"), "codigo com espacos")
        self.assertEqual(saida.getvalue(), "")

    def test_a_mensagem_diz_o_nome_e_nunca_o_valor(self) -> None:
        registo, _ = _novo(estrito=True)
        for canario in CANARIOS.values():
            with self.assertRaises(CampoRejeitado) as capturado:
                registo.info(canario, telefone=canario, outcome=canario, svc=canario,
                             ts=canario, **{canario: canario})
            mensagem = str(capturado.exception)
            self.assertIn("campo_reservado (svc)", mensagem)
            self.assertNotIn(canario, mensagem)
            self.assertIn("campo_desconhecido (telefone)", mensagem)
            self.assertIn("valor_invalido (outcome)", mensagem)
            self.assertIn("campo_desconhecido (<nome ilegivel>)", mensagem)
            self.assertIn("mensagem_livre (<posicional>)", mensagem)
            self.assertNotIn(canario, repr(capturado.exception.rejeicoes))

    def test_uma_chamada_limpa_escreve_normalmente(self) -> None:
        registo, saida = _novo(estrito=True)
        registo.info(outcome="ok", tenant_id=TENANT)
        registo.excepcao(ValueError("x"), "entrega_falhada")
        self.assertEqual(len(_linhas(saida)), 2)

    def test_liga_se_pela_variavel_de_ambiente_e_so_com_1(self) -> None:
        for valor, esperado in (("1", True), ("0", False), ("", False), ("true", False)):
            with self.subTest(valor=valor):
                with mock.patch.dict(os.environ, {VARIAVEL_ESTRITO: valor}):
                    self.assertEqual(Logger("gwy", destino=io.StringIO()).estrito, esperado)
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(VARIAVEL_ESTRITO, None)
            self.assertFalse(Logger("gwy", destino=io.StringIO()).estrito)
        with mock.patch.dict(os.environ, {VARIAVEL_ESTRITO: "1"}):
            self.assertFalse(Logger("gwy", destino=io.StringIO(), estrito=False).estrito)

    def test_tolerante_e_o_mesmo_logger_fora_do_modo_estrito(self) -> None:
        registo, saida = _novo(estrito=True)
        tolerante = registo.tolerante()
        self.assertFalse(tolerante.estrito)
        self.assertEqual(tolerante.svc, registo.svc)
        tolerante.info(telefone="923456789", outcome="ok")
        self.assertEqual(_linhas(saida), [
            {"ts": "2026-01-01T00:00:00.000Z", "level": "info", "svc": "paridade", "outcome": "ok"}
        ])


class TestAuxiliares(unittest.TestCase):
    def test_id_opaco_nao_deixa_ver_o_que_resume(self) -> None:
        opaco = id_opaco(CANARIOS["wamid"])
        self.assertRegex(opaco, r"^m_[0-9a-f]{32}$")
        self.assertNotIn("244923456789", opaco)
        self.assertEqual(opaco, id_opaco(CANARIOS["wamid"]))
        self.assertNotEqual(opaco, id_opaco(CANARIOS["wamid"] + "x"))

    def test_id_opaco_recusa_o_que_nao_e_texto(self) -> None:
        for valor in ("", None, 923456789, b"wamid", ["wamid"]):
            with self.subTest(valor=repr(valor)):
                with self.assertRaises(TypeError) as capturado:
                    id_opaco(valor)  # type: ignore[arg-type]
                self.assertNotIn("923456789", str(capturado.exception))

    def test_a_mascara_mostra_tres_caracteres_e_esconde_o_comprimento(self) -> None:
        self.assertEqual(mascarar_referencia("123456789"), "***789")
        self.assertEqual(len(mascarar_referencia("1" * 40)), 6)
        self.assertEqual(len(mascarar_referencia("12345678")), 6)

    def test_o_que_a_mascara_devolve_nao_cabe_em_campo_nenhum(self) -> None:
        """A *allowlist* e exacta: nao ha onde por uma referencia, nem mascarada."""
        mascarada = mascarar_referencia("123456789")
        for campo in CAMPOS_DE_CHAMADA:
            self.assertIsNone(politica.validar(campo, mascarada), campo)

    def test_nome_legivel(self) -> None:
        for nome in ("telefone", "X-Signature", "webhook_token", "a" * 40):
            self.assertEqual(politica.nome_legivel(nome), nome)
        for nome in ("+244 923 456 789", "x923456789", "a" * 41, "", 5, None, "com espaco",
                     "evt_3kQ9xZ2mP7aLw8Tn5VbR1cYd", "nif2", "_privado", "a__b"):
            self.assertEqual(politica.nome_legivel(nome), "<nome ilegivel>")

    def test_codigo_com_classe(self) -> None:
        self.assertEqual(politica.codigo_com_classe("c", "ValueError"), "c:ValueError")
        for classe in (None, 5, "", "com espaco", "E923456789", "A1b2C3d4", "E" * 65, "a:b"):
            self.assertEqual(politica.codigo_com_classe("c", classe), "c")
        self.assertEqual(politica.codigo_com_classe(5, "ValueError"), 5)

    def test_o_modulo_exporta_o_que_documenta(self) -> None:
        for nome in logger.__all__:
            self.assertTrue(hasattr(logger, nome), nome)


if __name__ == "__main__":
    unittest.main()
