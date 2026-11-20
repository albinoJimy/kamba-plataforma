"""O processo das fases de dados do off-boarding (KAM-218, criterio 1).

O que se mede aqui, sem base nem rede: o processo **arranca em `prod`** com as
credenciais todas, e **nao arranca** sem cada uma delas — pelo `main`, e nao so
pela funcao de configuracao, porque e o codigo de saida que o *compose* ve; a
chave do certificado leva o `kid`; a volta corre e nao morre; a sonda responde;
e os tres *compose* dizem o mesmo que o codigo (a porta, o comando, os segredos
e o ciclo das copias, confrontado com o `infra/backup/cobertura.yaml`).
"""

from __future__ import annotations

import base64
import json
import re
import threading
import unittest
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from kamba_core.offboarding import processo
from kamba_core.offboarding.processo import PortaSemAdaptador, ResultadoDaVolta, entrega_sem_adaptador
from kamba_core.offboarding.servico import (
    PORTA_POR_OMISSAO,
    SEGREDO_DO_CERTIFICADO,
    SEGREDOS_OBRIGATORIOS,
    SERVICO,
    VAR_COPIAS,
    ChaveDoCertificadoInvalida,
    Ciclo,
    ConfiguracaoEmFalta,
    chave_do_certificado,
    desfecho,
    ler_configuracao,
    montar_portas,
    servidor,
)
from kamba_core.storage.config import DestinoSemApdRefError
from kamba_core.storage.fake import MotorEmMemoria
from kamba_core.storage.guarda import ArmazenamentoPorTenant

RAIZ = Path(__file__).resolve().parents[3]
CHAVE = base64.b64encode(b"k" * 32).decode()
SENHA = "senha-de-ensaio-nao-e-segredo"


def ambiente(nome: str = "prod", **mudancas: str | None) -> dict[str, str]:
    env = {
        "KAMBA_ENV": nome,
        "KAMBA_DB_NAME": "kamba",
        "KAMBA_SECRET_DB_APP_PASSWORD": SENHA,
        "KAMBA_SECRET_DB_BATCH_PASSWORD": SENHA,
        "KAMBA_SECRET_DB_IDENTITY_PASSWORD": SENHA,
        VAR_COPIAS: "35",
        "KAMBA_STORAGE_ENDPOINT": "http://sto:8333",
        "KAMBA_STORAGE_BUCKET": "kamba-objectos",
        "KAMBA_STORAGE_REGION": "ao-luanda-1",
        "KAMBA_STORAGE_DESTINO_COUNTRY": "AO",
        "KAMBA_STORAGE_DESTINO_PROVIDER": "seaweedfs",
        "KAMBA_SECRET_STORAGE_ACCESS_KEY_ID": "id-de-ensaio",
        "KAMBA_SECRET_STORAGE_SECRET_ACCESS_KEY": "segredo-de-ensaio",
        "KAMBA_SECRET_OFFBOARDING_CERTIFICATE_KEY": f"cert-2026-11:{CHAVE}",
    }
    for nome_da_var, valor in mudancas.items():
        if valor is None:
            env.pop(nome_da_var, None)
        else:
            env[nome_da_var] = valor
    return env


class Segredos:
    def __init__(self, valor: str) -> None:
        self.valor = valor
        self.pedidos: list[str] = []

    def get(self, ref: str) -> str:
        self.pedidos.append(ref)
        return self.valor


class TestConfiguracao(unittest.TestCase):
    def test_arranca_em_prod_com_as_credenciais(self) -> None:
        c = ler_configuracao(ambiente("prod"))
        self.assertEqual((c.ambiente, c.porta, c.copias_dias), ("prod", PORTA_POR_OMISSAO, 35))
        self.assertEqual(c.intervalo_s, 900)

    def test_sem_cada_credencial_nao_arranca_e_a_mensagem_diz_qual_sem_o_valor(self) -> None:
        for falta in ("KAMBA_ENV", "KAMBA_DB_NAME", "KAMBA_SECRET_DB_APP_PASSWORD",
                      "KAMBA_SECRET_DB_BATCH_PASSWORD", "KAMBA_SECRET_DB_IDENTITY_PASSWORD", VAR_COPIAS):
            with self.subTest(falta=falta):
                with self.assertRaises(ConfiguracaoEmFalta) as erro:
                    ler_configuracao(ambiente(**{falta: None}))
                self.assertIn(falta, str(erro.exception))
                self.assertNotIn(SENHA, str(erro.exception))

    def test_um_ambiente_fora_do_dominio_ou_um_inteiro_invalido_recusa(self) -> None:
        for mudanca in ({"KAMBA_ENV": "production"}, {VAR_COPIAS: "0"}, {VAR_COPIAS: "35d"},
                        {"OFFBOARDING_DADOS_PORT": "70000"}, {"KAMBA_OFFBOARDING_INTERVALO_S": "-1"}):
            with self.subTest(mudanca=mudanca), self.assertRaises(ConfiguracaoEmFalta):
                ler_configuracao(ambiente(**mudanca))

    def test_em_prod_o_armazenamento_fora_de_angola_sem_apd_ref_nao_arranca(self) -> None:
        with self.assertRaises(DestinoSemApdRefError):
            ler_configuracao(ambiente(KAMBA_STORAGE_DESTINO_COUNTRY="PT"))
        ler_configuracao(ambiente("staging", KAMBA_STORAGE_DESTINO_COUNTRY="PT"))


class TestChaveDoCertificado(unittest.TestCase):
    def test_o_kid_vem_do_valor(self) -> None:
        self.assertEqual(chave_do_certificado(f"cert-2026-11:{CHAVE}"), ("cert-2026-11", b"k" * 32))

    def test_um_valor_sem_kid_recusa_sem_o_dizer(self) -> None:
        for valor in (CHAVE, "actual:" + CHAVE, "k1:" + base64.b64encode(b"k" * 16).decode(), "x"):
            with self.subTest(valor=valor[:6]), self.assertRaises(ChaveDoCertificadoInvalida) as erro:
                chave_do_certificado(valor)
            self.assertNotIn(CHAVE, str(erro.exception))

    def test_as_portas_levam_a_chave_o_ciclo_e_a_entrega_sem_adaptador(self) -> None:
        sto = ArmazenamentoPorTenant(MotorEmMemoria())
        segredos = Segredos(f"cert-2026-11:{CHAVE}")
        portas = montar_portas(ler_configuracao(ambiente()), segredos, sto)
        self.assertEqual(segredos.pedidos, [SEGREDO_DO_CERTIFICADO])
        self.assertEqual((portas.kid_do_certificado, portas.chave_do_certificado), ("cert-2026-11", b"k" * 32))
        self.assertEqual(portas.copias_expiram_em_dias, 35)
        self.assertIs(portas.armazenamento, sto)
        self.assertIsNone(portas.anos_fiscais, "o prazo do CGT continua NAO VERIFICADO")
        self.assertIs(portas.entregar, entrega_sem_adaptador)
        with self.assertRaises(PortaSemAdaptador):
            portas.entregar("t", b"{}")


class TestOProcessoPeloMain(unittest.TestCase):
    """O codigo de saida e o que o *compose* ve: 2 sem credenciais, em qualquer ambiente."""

    def correr(self, env: dict[str, str]) -> int:
        from kamba_core.offboarding.__main__ import main

        return main(env)

    def test_sem_cada_segredo_obrigatorio_sai_com_2(self) -> None:
        for ref in SEGREDOS_OBRIGATORIOS:
            with self.subTest(ref=ref):
                self.assertEqual(self.correr(ambiente(**{f"KAMBA_SECRET_{ref.upper()}": None})), 2)

    def test_sem_a_base_ou_com_a_chave_sem_kid_sai_com_2(self) -> None:
        self.assertEqual(self.correr(ambiente(KAMBA_SECRET_DB_BATCH_PASSWORD=None)), 2)
        self.assertEqual(self.correr(ambiente(KAMBA_SECRET_OFFBOARDING_CERTIFICATE_KEY=CHAVE)), 2)


class TestCiclo(unittest.TestCase):
    def test_corre_a_volta_e_uma_que_levanta_nao_mata_o_ciclo(self) -> None:
        parar = threading.Event()
        voltas: list[ResultadoDaVolta] = []
        falhas: list[BaseException] = []
        original = processo.correr_volta
        chamadas = {"n": 0}

        def volta_falsa(*_args, **_kw):
            chamadas["n"] += 1
            if chamadas["n"] == 1:
                raise RuntimeError("primeira volta")
            if chamadas["n"] >= 3:
                parar.set()
            return ResultadoDaVolta(feitas={"purga": 1})

        import kamba_core.offboarding.servico as servico

        servico.correr_volta = volta_falsa
        try:
            ciclo = Ciclo(lambda: None, lambda: None, object(), relogio=lambda: datetime(2026, 11, 20, tzinfo=UTC))
            ciclo.correr(parar, 0, voltas.append, falhas.append)
        finally:
            servico.correr_volta = original
        self.assertEqual(len(falhas), 1)
        self.assertEqual(len(voltas), 2)

    def test_o_desfecho_diz_as_fases_que_falharam_e_nunca_o_tenant(self) -> None:
        self.assertEqual(desfecho(ResultadoDaVolta()), ("offboarding_dados_volta_concluida", None))
        self.assertEqual(desfecho(ResultadoDaVolta(falhas=["purga", "certificado"])),
                         ("offboarding_dados_volta_com_falhas", "purga,certificado"))


class TestSonda(unittest.TestCase):
    def test_healthz_responde_e_o_resto_nao(self) -> None:
        http = servidor(0, {"KAMBA_COMMIT_SHA": "abc1234"})
        fio = threading.Thread(target=http.serve_forever, daemon=True)
        fio.start()
        try:
            porta = http.server_address[1]
            with urllib.request.urlopen(f"http://127.0.0.1:{porta}/healthz", timeout=4) as r:
                corpo = json.loads(r.read())
            self.assertEqual((r.status, corpo["service"], corpo["commit"]), (200, SERVICO, "abc1234"))
            with self.assertRaises(urllib.error.HTTPError) as erro:
                urllib.request.urlopen(f"http://127.0.0.1:{porta}/metrics", timeout=4)
            self.assertEqual(erro.exception.code, 404)
        finally:
            http.shutdown()
            http.server_close()


def bloco_do_servico(texto: str, nome: str) -> str:
    """O bloco de um servico no *compose*: da linha `  nome:` a proxima chave do mesmo nivel."""
    m = re.search(rf"^  {re.escape(nome)}:\n(.*?)(?=^  [a-z][a-z0-9-]*:\n|^[a-z]|\Z)", texto, re.M | re.S)
    if m is None:
        raise AssertionError(f"o servico {nome} nao esta no compose")
    return m.group(1)


class TestCompose(unittest.TestCase):
    """Os tres *compose* dizem o que o codigo diz, e o ciclo das copias e o do repositorio."""

    def test_o_servico_esta_nos_tres_ambientes_com_o_que_o_codigo_le(self) -> None:
        cobertura = (RAIZ / "infra/backup/cobertura.yaml").read_text(encoding="utf-8")
        dias = re.search(r"^\s*retencao_dias:\s*(\d+)", cobertura, re.M)
        self.assertIsNotNone(dias)
        for amb in ("dev", "staging", "prod"):
            with self.subTest(ambiente=amb):
                texto = (RAIZ / f"infra/compose/docker-compose.{amb}.yml").read_text(encoding="utf-8")
                bloco = bloco_do_servico(texto, "offboarding-dados")
                self.assertIn('command: ["python", "-m", "kamba_core.offboarding"]', bloco)
                self.assertIn(f'OFFBOARDING_DADOS_PORT: "{PORTA_POR_OMISSAO}"', bloco)
                self.assertIn(f"127.0.0.1:{PORTA_POR_OMISSAO}/healthz", bloco)
                self.assertIn(f'{VAR_COPIAS}: "{dias.group(1)}"', bloco)
                self.assertIn(f"KAMBA_ENV: {amb}", bloco)
                for ref in SEGREDOS_OBRIGATORIOS:
                    self.assertIn(f"KAMBA_SECRET_{ref.upper()}:", bloco)
                for var in ("KAMBA_SECRET_DB_APP_PASSWORD", "KAMBA_SECRET_DB_BATCH_PASSWORD",
                            "KAMBA_SECRET_DB_IDENTITY_PASSWORD", "KAMBA_DB_NAME"):
                    self.assertIn(f"{var}:", bloco)

    def test_o_segredo_do_certificado_esta_no_inventario_com_kid(self) -> None:
        inventario = (RAIZ / "ops/secrets-inventory.yaml").read_text(encoding="utf-8")
        m = re.search(rf"^  - id: {SEGREDO_DO_CERTIFICADO}\n(.*?)(?=^  - id: |\Z)", inventario, re.M | re.S)
        self.assertIsNotNone(m)
        self.assertRegex(m.group(1), r"(?m)^    kid: true$")
        self.assertRegex(m.group(1), r"(?m)^    obrigatorio_em: \[dev, staging, prod\]$")


if __name__ == "__main__":
    unittest.main()
