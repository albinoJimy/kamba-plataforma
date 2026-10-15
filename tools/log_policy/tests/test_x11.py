"""X-11: o varrimento ve o que tem de ver, e o *logger* nao lhe da nada para ver.

Duas metades, e a ordem importa:

1. **O varrimento morde.** Cada padrao e provado com uma linha que o tem. Sem
   isto, «zero achados» nas 1 000 *fixtures* nao queria dizer nada.
2. **As 1 000 *fixtures* dao zero** — pelo *logger* e pela ponte — e o controlo
   positivo confirma que os padroes veem os identificadores na entrada.

O espelho em TypeScript corre no `make x11` (gate 6), onde a saida das duas
linguagens se compara byte a byte; aqui prova-se o lado Python e o varrimento.
"""

from __future__ import annotations

import base64
import json
import re
import unittest
from pathlib import Path

from kamba_core.logger import politica
from log_policy import cli, conduzir, fixtures, x11

ROOT = Path(__file__).resolve().parents[3]
SEM_NIF = x11.Configuracao.criar()
TENANT = "0b6f1d2e-3c4a-4b5c-8d6e-7f8091a2b3c4"
#: Um UUID valido cujo ultimo grupo sao doze digitos comecados por 9.
TENANT_COM_DIGITOS = "0b6f1d2e-3c4a-4b5c-8d6e-923456789012"


def _linha(**campos) -> str:
    base = {"ts": "2026-01-01T00:00:00.000Z", "level": "info", "svc": "gwy"}
    base.update(campos)
    return json.dumps(base, separators=(",", ":"))


def _padroes(texto: str, configuracao: x11.Configuracao = SEM_NIF) -> set[str]:
    return {padrao for padrao, _ in x11.varrer_linha(texto, configuracao)}


class TestOsTresCatalogosDeCamposSaoUmSo(unittest.TestCase):
    """O varrimento nao importa a lista do *logger*; confere-se aqui que e a mesma."""

    def test_python(self) -> None:
        self.assertEqual(x11.CAMPOS, politica.CAMPOS)
        self.assertEqual(fixtures.CAMPOS_DE_CHAMADA, politica.CAMPOS_DE_CHAMADA)

    def test_typescript(self) -> None:
        fonte = (ROOT / "packages/core-ts/src/logger/politica.ts").read_text(encoding="utf-8")
        bloco = re.search(r"export const CAMPOS = \[(.*?)\] as const;", fonte, re.S)
        self.assertIsNotNone(bloco)
        self.assertEqual(tuple(re.findall(r'"([a-z_]+)"', bloco.group(1))), x11.CAMPOS)
        chamada = re.search(r"export const CAMPOS_DE_CHAMADA = \[(.*?)\] as const;", fonte, re.S)
        self.assertEqual(
            tuple(re.findall(r'"([a-z_]+)"', chamada.group(1))), politica.CAMPOS_DE_CHAMADA
        )
        interface = re.search(r"export interface CamposDeLog \{(.*?)\n\}", fonte, re.S)
        self.assertEqual(
            tuple(re.findall(r"readonly ([a-z_]+)\?:", interface.group(1))),
            politica.CAMPOS_DE_CHAMADA,
        )


class TestOVarrimentoMorde(unittest.TestCase):
    def test_uma_linha_limpa_nao_da_nada(self) -> None:
        linha = _linha(tenant_id=TENANT, contact_hmac_prefix="a1b2c3d4", turn_id=TENANT,
                       msg_id="m_" + "0" * 32, wa_type="text", latency_ms=99999999,
                       tool="criar_pedido", outcome="ok", error_code="131049")
        self.assertEqual(x11.varrer_linha(linha, SEM_NIF), [])

    def test_os_formatos_de_telefone_do_criterio(self) -> None:
        formatos = (
            "+244 923 456 789", "+244923456789", "244 923 456 789", "244923456789",
            "00244923456789", "(+244) 923-456-789", "923456789", "923 456 789",
            "923-456-789", "923.456.789",
        )
        for formato in formatos:
            with self.subTest(formato=formato):
                em_campo = _padroes(_linha(outcome=formato))
                self.assertTrue(
                    em_campo & {x11.TELEFONE_INTERNACIONAL, x11.TELEFONE_NACIONAL}, em_campo
                )
                em_texto = _padroes(f"pedido de {formato} recebido")
                self.assertIn(x11.LINHA_FORA, em_texto)
                self.assertTrue(
                    em_texto & {x11.TELEFONE_INTERNACIONAL, x11.TELEFONE_NACIONAL}, em_texto
                )

    def test_o_telefone_e_visto_em_qualquer_campo_que_nao_tenha_a_sua_forma(self) -> None:
        for campo in x11.CAMPOS:
            with self.subTest(campo=campo):
                self.assertIn(x11.TELEFONE_NACIONAL, _padroes(_linha(**{campo: "923456789"})))
                self.assertIn(x11.TELEFONE_NACIONAL, _padroes(_linha(**{campo: 923456789})))

    def test_um_uuid_com_nove_digitos_nao_e_um_telefone(self) -> None:
        """A razao de o varrimento conhecer a forma da linha."""
        self.assertRegex(TENANT_COM_DIGITOS, r"9[0-9]{8}")
        for campo in ("tenant_id", "turn_id", "msg_id"):
            self.assertEqual(x11.varrer_linha(_linha(**{campo: TENANT_COM_DIGITOS}), SEM_NIF), [])
        self.assertEqual(
            x11.varrer_linha(_linha(msg_id="m_" + "923456789012" + "a" * 20), SEM_NIF), []
        )
        self.assertEqual(x11.varrer_linha(_linha(contact_hmac_prefix="92345678"), SEM_NIF), [])

    def test_mas_o_mesmo_uuid_fora_do_seu_campo_e_varrido(self) -> None:
        for campo in ("outcome", "tool", "error_code", "wa_type", "svc", "contact_hmac_prefix"):
            with self.subTest(campo=campo):
                self.assertIn(
                    x11.TELEFONE_NACIONAL, _padroes(_linha(**{campo: TENANT_COM_DIGITOS}))
                )

    def test_um_quase_uuid_num_campo_de_forma_fechada_e_varrido(self) -> None:
        for valor in (TENANT_COM_DIGITOS + " ", TENANT_COM_DIGITOS.upper(),
                      "x" + TENANT_COM_DIGITOS, TENANT_COM_DIGITOS.replace("-", "")):
            with self.subTest(valor=valor):
                self.assertIn(x11.TELEFONE_NACIONAL, _padroes(_linha(tenant_id=valor)))

    def test_um_ts_que_nao_e_um_ts_e_varrido(self) -> None:
        self.assertEqual(x11.varrer_linha(_linha(), SEM_NIF), [])
        self.assertIn(x11.TELEFONE_NACIONAL, _padroes(_linha(ts="923456789")))

    def test_formas_que_a_revisao_mostrou_a_passar(self) -> None:
        """Achado A9: cada uma destas dava `[]` na primeira versao."""
        for valor in (
            "923_456_789", "923/456/789", "923,456,789", "923  456  789", "923456__789",
            "\uff19\uff12\uff13\uff14\uff15\uff16\uff17\uff18\uff19",          # largura total
            "9\u0662\u0663\u0664\u0665\u0666\u0667\u0668\u0669",                # arabe-indicos
            "923\u200b456\u200b789", "923\u2060456\ufeff789",                      # largura zero
        ):
            with self.subTest(valor=valor.encode("unicode_escape").decode()):
                self.assertIn(x11.TELEFONE_NACIONAL, _padroes(_linha(outcome=valor)))
                self.assertIn(x11.TELEFONE_NACIONAL, _padroes(f"cliente {valor} pagou"))
        self.assertIn(x11.TELEFONE_INTERNACIONAL, _padroes(_linha(outcome="244..923456..789")))

    def test_uma_chave_repetida_nao_esconde_a_primeira(self) -> None:
        linha = '{"ts":"2026-01-01T00:00:00.000Z","level":"info","svc":"gwy","outcome":"923456789","outcome":"ok"}'
        self.assertIn((x11.TELEFONE_NACIONAL, "outcome"), x11.varrer_linha(linha, SEM_NIF))
        aninhada = '{"svc":"gwy","outcome":{"a":"923456789","a":"ok"}}'
        self.assertIn((x11.TELEFONE_NACIONAL, "outcome"), x11.varrer_linha(aninhada, SEM_NIF))

    def test_um_id_opaco_fora_do_seu_campo_e_varrido(self) -> None:
        opaco = "m_" + "923456789012" + "a" * 20
        self.assertEqual(x11.varrer_linha(_linha(msg_id=opaco), SEM_NIF), [])
        for campo in ("tenant_id", "contact_hmac_prefix", "outcome"):
            self.assertIn(x11.TELEFONE_NACIONAL, _padroes(_linha(**{campo: opaco})), campo)

    def test_email_iban_e_sequencias_de_digitos(self) -> None:
        self.assertIn(x11.EMAIL, _padroes(_linha(outcome="joaquina.canario@exemplo.co.ao")))
        self.assertIn(x11.IBAN_AO, _padroes(_linha(outcome="AO06004000001234567890123")))
        self.assertIn(x11.IBAN_AO, _padroes(_linha(outcome="AO06 0040 0000 1234 5678 9012 3")))
        self.assertIn(x11.SEQUENCIA_DE_DIGITOS, _padroes(_linha(error_code="5417123456")))
        self.assertIn(x11.SEQUENCIA_DE_DIGITOS, _padroes(_linha(outcome="00123 456 789 012")))
        self.assertEqual(_padroes(_linha(error_code="12345678")), set())

    def test_segredos_com_forma_conhecida(self) -> None:
        token = "EAA" + "x9" * 40
        self.assertIn(x11.SEGREDO, _padroes(_linha(error_code=token)))
        jwt = ".".join(("eyJ" + "a1" * 10, "b2" * 12, "c3" * 12))
        self.assertIn(x11.SEGREDO, _padroes(f"Authorization: Bearer {jwt}"))

    def test_um_telefone_dentro_de_base64(self) -> None:
        """O identificador de mensagem da Meta leva o numero la dentro."""
        bruto = bytes((0x1C, 0x18, 12)) + b"244923456789" + bytes(range(12))
        wamid = "wamid." + base64.b64encode(bruto).decode("ascii")
        self.assertNotRegex(wamid, r"9[0-9]{8}")
        self.assertIn(x11.BASE64_COM_IDENTIFICADOR, _padroes(_linha(msg_id=wamid)))
        self.assertIn(x11.BASE64_COM_IDENTIFICADOR, _padroes(f"recebido {wamid} de alguem"))
        url = base64.urlsafe_b64encode(b"\xff\xfe\xfd" + b"cliente 923456789 pagou").decode("ascii")
        self.assertIn(x11.BASE64_COM_IDENTIFICADOR, _padroes(_linha(outcome=url)))
        inocente = base64.b64encode(b"nada de especial aqui dentro").decode("ascii")
        self.assertEqual(_padroes(_linha(outcome=inocente)), set())

    def test_campo_fora_da_allowlist(self) -> None:
        achados = x11.varrer_linha(_linha(telefone="923456789"), SEM_NIF)
        self.assertIn((x11.CAMPO_FORA, "telefone"), achados)
        self.assertIn((x11.TELEFONE_NACIONAL, "telefone"), achados)
        self.assertEqual(
            x11.varrer_linha(_linha(event="service.started"), SEM_NIF), [(x11.CAMPO_FORA, "event")]
        )

    def test_o_conteudo_na_chave_tambem_e_visto_e_nao_e_repetido(self) -> None:
        achados = x11.varrer_linha(_linha(**{"923456789": "ok"}), SEM_NIF)
        self.assertIn((x11.CAMPO_FORA, "<chave ilegivel>"), achados)
        self.assertIn((x11.TELEFONE_NACIONAL, "<chave>"), achados)
        self.assertNotIn("923456789", repr(achados))

    def test_valores_aninhados_sao_varridos(self) -> None:
        linha = _linha(outcome={"a": [{"b": "923456789"}]}, tool=["x", 244923456789])
        achados = x11.varrer_linha(linha, SEM_NIF)
        self.assertIn((x11.TELEFONE_NACIONAL, "outcome"), achados)
        self.assertIn((x11.TELEFONE_INTERNACIONAL, "tool"), achados)

    def test_o_que_nao_e_um_objecto_json_e_fora_do_formato(self) -> None:
        for texto in ("INFO: Uvicorn running on http://0.0.0.0:8000", "[1, 2]", '"texto"',
                      "{mal formado", "42", "null"):
            with self.subTest(texto=texto):
                self.assertIn(x11.LINHA_FORA, _padroes(texto))


class TestNifParametrizavel(unittest.TestCase):
    """O formato nao esta definido em documento nenhum: e um parametro."""

    #: Exemplos de forma, **nao** a definicao do NIF.
    EXEMPLOS = (r"\b[0-9]{9}[A-Z]{2}[0-9]{3}\b", r"\bNIF[: ]+[0-9]{4}\b")

    def test_sem_padrao_o_nif_so_e_visto_como_sequencia_de_digitos(self) -> None:
        self.assertEqual(_padroes(_linha(outcome="004567890LA045")), {x11.SEQUENCIA_DE_DIGITOS})
        self.assertEqual(_padroes(_linha(outcome="NIF 1234")), set())

    def test_com_padrao_e_visto_como_nif(self) -> None:
        configuracao = x11.Configuracao.criar(nif_padroes=self.EXEMPLOS)
        self.assertIn(x11.NIF, _padroes(_linha(outcome="004567890LA045"), configuracao))
        self.assertIn(x11.NIF, _padroes(_linha(outcome="NIF 1234"), configuracao))
        self.assertIn(x11.NIF, _padroes("o NIF: 1234 do cliente", configuracao))
        self.assertNotIn(x11.NIF, _padroes(_linha(outcome="ok"), configuracao))

    def test_um_padrao_que_nao_compila_e_erro_de_configuracao(self) -> None:
        with self.assertRaises(x11.ConfiguracaoInvalida) as capturado:
            x11.Configuracao.criar(nif_padroes=("[0-9",))
        self.assertNotIn("[0-9", str(capturado.exception))


class TestCanariosEAchados(unittest.TestCase):
    def test_um_canario_e_procurado_por_cadeia_exacta(self) -> None:
        configuracao = x11.Configuracao.criar(canarios=("Joaquina Canario", "", "CANARIO-TEXTO-1"))
        self.assertEqual(configuracao.canarios, ("Joaquina Canario", "CANARIO-TEXTO-1"))
        self.assertIn(x11.CANARIO, _padroes(_linha(outcome="Joaquina Canario"), configuracao))
        self.assertIn(x11.CANARIO, _padroes("texto [CANARIO-TEXTO-1] livre", configuracao))
        self.assertNotIn(x11.CANARIO, _padroes(_linha(outcome="ok"), configuracao))

    def test_um_achado_nunca_leva_o_valor(self) -> None:
        conteudo = "\n".join(
            (
                _linha(outcome="ok"),
                "",
                _linha(telefone="+244 923 456 789", outcome="joaquina@exemplo.co.ao"),
                "pedido de 923456789 falhou",
            )
        )
        achados, linhas = x11.varrer_texto("gwy.log", conteudo, SEM_NIF)
        self.assertEqual(linhas, 3)
        self.assertEqual({a.linha for a in achados}, {3, 4})
        for achado in achados:
            for proibido in ("923", "joaquina", "exemplo"):
                self.assertNotIn(proibido, str(achado))
                self.assertNotIn(proibido, repr(achado))
        self.assertIn("gwy.log:3: campo_fora_da_allowlist em telefone", [str(a) for a in achados])

    def test_varrer_ficheiro(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "agr.log"
            caminho.write_text(_linha(outcome="923456789") + "\n", encoding="utf-8")
            achados, linhas = x11.varrer_ficheiro(caminho, SEM_NIF)
            self.assertEqual((linhas, [a.padrao for a in achados][:1]), (1, [x11.TELEFONE_NACIONAL]))
            with self.assertRaises(x11.ConfiguracaoInvalida):
                x11.varrer_ficheiro(Path(pasta) / "nao-existe.log", SEM_NIF)


class TestFixtures(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixtures = fixtures.gerar()

    def test_sao_mil_e_sao_sempre_as_mesmas(self) -> None:
        self.assertEqual(len(self.fixtures), 1000)
        self.assertEqual(fixtures.gerar(), self.fixtures)
        self.assertNotEqual(fixtures.gerar(semente=69), self.fixtures)
        self.assertEqual([f["id"] for f in self.fixtures], list(range(1000)))

    def test_cobrem_todas_as_classes_por_todas_as_rotas(self) -> None:
        vistas = {(f["classe"], f["rota"]) for f in self.fixtures}
        for classe in fixtures.CLASSES:
            for rota in fixtures.ROTAS:
                if rota in fixtures.ROTAS_TRANSFORMADAS and classe not in fixtures.CLASSES_COM_DIGITOS:
                    self.assertNotIn((classe, rota), vistas)
                else:
                    self.assertIn((classe, rota), vistas)
        self.assertEqual(len({f["classe"] for f in self.fixtures}), 10)
        self.assertEqual(len({f["rota"] for f in self.fixtures}), 11)

    def test_todas_tem_canarios_e_os_canarios_estao_na_chamada(self) -> None:
        for fixture in self.fixtures:
            self.assertTrue(fixture["canarios"], fixture["id"])
            chamada = json.dumps(fixture["chamada"], ensure_ascii=False)
            for canario in fixture["canarios"]:
                self.assertGreaterEqual(len(canario), 6)
                if fixture["classe"] != "wamid":
                    self.assertIn(canario, chamada, fixture["id"])

    def test_o_wamid_leva_o_numero_la_dentro(self) -> None:
        for fixture in (f for f in self.fixtures if f["classe"] == "wamid"):
            corpo = fixture["valor"].split(".", 1)[1]
            self.assertIn(fixture["canarios"][0].encode(), base64.b64decode(corpo))
            self.assertNotIn(fixture["canarios"][0], fixture["valor"])

    def test_os_formatos_de_telefone_do_criterio_estao_todos_la(self) -> None:
        telefones = [f["valor"] for f in self.fixtures if f["classe"] == "telefone"]
        self.assertTrue(any(re.fullmatch(r"\+244 9\d\d \d{3} \d{3}", t) for t in telefones))
        self.assertTrue(any(re.fullmatch(r"244 9\d\d \d{3} \d{3}", t) for t in telefones))
        self.assertTrue(any(re.fullmatch(r"2449\d{8}", t) for t in telefones))
        self.assertTrue(any(re.fullmatch(r"9\d{8}", t) for t in telefones))

    def test_um_conjunto_sem_uma_combinacao_e_recusado(self) -> None:
        fixtures._exigir_cobertura(self.fixtures)
        sem_uma = [
            f for f in self.fixtures if (f["classe"], f["rota"]) != ("telefone", "chave")
        ]
        self.assertGreater(len(sem_uma), 900)
        with self.assertRaises(AssertionError):
            fixtures._exigir_cobertura(sem_uma)
        sem_transformada = [
            f for f in self.fixtures if (f["classe"], f["rota"]) != ("iban", "embutido")
        ]
        with self.assertRaises(AssertionError):
            fixtures._exigir_cobertura(sem_transformada)

    def test_um_conjunto_pequeno_pedido_de_proposito_passa(self) -> None:
        self.assertEqual(len(fixtures.gerar(quantas=7)), 7)


class TestFixturesDeForma(unittest.TestCase):
    """As trinta que exercitam o que a rotacao de canarios nao exercita.

    A primeira revisao mutou as duas implementacoes ao mesmo tempo — tecto de
    `latency_ms`, forma por palavras, formas de segredo — e o `make x11`
    continuou verde, porque nenhuma *fixture* levava um valor que so essas
    regras recusam. Aqui prova-se, regra a regra, que agora leva.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.extras = fixtures.gerar_extras()
        cls.configuracao = x11.Configuracao.criar(
            canarios=[c for f in cls.extras for c in f["canarios"]]
        )

    def test_sao_trinta_dez_por_rota_e_sempre_as_mesmas(self) -> None:
        self.assertEqual(len(self.extras), 30)
        self.assertEqual(fixtures.gerar_extras(), self.extras)
        self.assertEqual([f["id"] for f in self.extras], list(range(1000, 1030)))
        for rota in fixtures.ROTAS_DE_FORMA:
            self.assertEqual(sum(f["rota"] == rota for f in self.extras), 10)

    def test_cada_valor_so_e_recusado_pela_sua_regra(self) -> None:
        """Se a regra visada saisse, o valor passava — e por isso a exercita."""
        for fixture in self.extras:
            campos = fixture["chamada"]["campos"]
            valor = fixture["valor"]
            with self.subTest(rota=fixture["rota"], valor=valor):
                if fixture["rota"] == "numero":
                    self.assertEqual(campos["latency_ms"], int(valor))
                    self.assertRegex(valor, r"^9[0-9]{8}$")
                    self.assertIsNone(politica.validar("latency_ms", int(valor)))
                    self.assertEqual(politica.validar("latency_ms", int(valor[:8])), int(valor[:8]))
                elif fixture["rota"] == "identificador_ma_forma":
                    campo = next(c for c, v in campos.items() if v == valor)
                    self.assertIsNone(politica.validar(campo, valor))
                    self.assertRegex(valor, r"^[a-z][a-z0-9]*$")
                    self.assertEqual(sum(c.isdigit() for c in valor), 6)
                else:
                    self.assertIsNone(politica.validar("error_code", valor))
                    sem_prefixo = valor.replace("eyJ", "eyx").replace("EAA", "EXA")
                    self.assertEqual(politica.validar("error_code", sem_prefixo), sem_prefixo)

    def test_passam_pelo_logger_sem_deixar_nada(self) -> None:
        texto, contadores = conduzir.conduzir(self.extras)
        achados, linhas = x11.varrer_texto("extras.log", texto, self.configuracao)
        self.assertEqual((linhas, [str(a) for a in achados]), (30, []))
        self.assertEqual(contadores, {"log_field_rejected_total:valor_invalido": 30})

    def test_o_varrimento_ve_as_se_passarem(self) -> None:
        """A outra metade: uma linha com o valor la dentro e achado."""
        for fixture in self.extras:
            linha = json.dumps(
                {"ts": "2026-01-01T00:00:00.000Z", "level": "info", "svc": "x11",
                 **fixture["chamada"]["campos"]}
            )
            padroes = {p for p, _ in x11.varrer_linha(linha, self.configuracao)}
            self.assertIn(x11.CANARIO, padroes, fixture["valor"])
            if fixture["rota"] == "numero":
                self.assertIn(x11.TELEFONE_NACIONAL, padroes)


class TestAsMilFixturesDaoZero(unittest.TestCase):
    """O criterio: 1 000 *fixtures*, 0 correspondencias nos *logs* gerados."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.fixtures = fixtures.gerar()
        cls.canarios = [c for f in cls.fixtures for c in f["canarios"]]
        cls.texto, cls.contadores = conduzir.conduzir(cls.fixtures)
        cls.configuracao = x11.Configuracao.criar(
            nif_padroes=TestNifParametrizavel.EXEMPLOS, canarios=cls.canarios
        )

    def test_as_classes_do_controlo_positivo_estao_fixas(self) -> None:
        self.assertEqual(
            cli.CLASSES_VISIVEIS_POR_PADRAO, ("telefone", "nif", "email", "iban", "wamid")
        )

    def test_controlo_positivo_os_padroes_veem_as_fixtures(self) -> None:
        controlo = cli.controlo_positivo(self.fixtures)
        for classe in cli.CLASSES_VISIVEIS_POR_PADRAO:
            vistas, total = controlo[classe]
            self.assertEqual((classe, vistas), (classe, total))
            self.assertEqual(total, 100)

    def test_controlo_positivo_a_entrada_crua_esta_cheia_de_achados(self) -> None:
        crua = "\n".join(json.dumps(f["chamada"], ensure_ascii=False) for f in self.fixtures)
        achados, linhas = x11.varrer_texto("entrada", crua, self.configuracao)
        self.assertEqual(linhas, 1000)
        self.assertEqual(len({a.linha for a in achados}), 1000)

    def test_uma_linha_por_fixture(self) -> None:
        self.assertEqual(self.texto.count("\n"), 1000)

    def test_zero_achados_nos_logs_gerados(self) -> None:
        achados, linhas = x11.varrer_texto("py.log", self.texto, self.configuracao)
        self.assertEqual(linhas, 1000)
        self.assertEqual([str(a) for a in achados], [])

    def test_zero_tambem_com_o_varrimento_cego_fora_dos_campos_de_forma_fechada(self) -> None:
        """Sem a leitura por campos: retira-se so o que tem forma de UUID."""
        fechados = re.compile(
            r'"(?:tenant_id|turn_id|msg_id)":"[0-9a-f-]{36}",|"ts":"[^"]+",'
        )
        for numero, linha in enumerate(self.texto.splitlines(), start=1):
            resto = fechados.sub("", linha)
            self.assertNotRegex(resto, r"9[0-9]{8}", numero)
            self.assertNotRegex(resto, r"[0-9]{7}", numero)
            self.assertNotIn("@", resto, numero)

    def test_todas_as_linhas_so_tem_campos_da_allowlist(self) -> None:
        for linha in self.texto.splitlines():
            objecto = json.loads(linha)
            self.assertLessEqual(set(objecto), set(x11.CAMPOS))
            self.assertEqual(objecto["svc"], "x11")

    def test_as_rejeicoes_foram_contadas(self) -> None:
        self.assertEqual(set(self.contadores), {f"log_field_rejected_total:{m}" for m in politica.MOTIVOS})
        self.assertGreaterEqual(sum(self.contadores.values()), 900)

    def test_zero_tambem_pela_ponte_do_logging(self) -> None:
        amostra = self.fixtures[::7]
        texto = conduzir.conduzir_ponte(amostra)
        achados, linhas = x11.varrer_texto("py.ponte.log", texto, self.configuracao)
        self.assertEqual(linhas, 10 * sum(len(f["canarios"]) for f in amostra))
        self.assertEqual([str(a) for a in achados], [])

    def test_a_ponte_repoe_o_estado_do_processo(self) -> None:
        import logging
        import sys

        antes = (list(logging.getLogger().handlers), sys.excepthook)
        conduzir.conduzir_ponte(self.fixtures[:2])
        self.assertEqual((list(logging.getLogger().handlers), sys.excepthook), antes)


if __name__ == "__main__":
    unittest.main()
