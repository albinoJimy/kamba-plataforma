"""A entrada de canal contra PostgreSQL e fila reais — KAM-013.

Esta suite e a que mede o que **nao se mede de dentro do processo**, e os
criterios do ticket pedem exactamente isso: «o 200 so e devolvido depois de o
*job* estar enfileirado», «com Redis indisponivel o GWY responde 503 e nunca
200», «a mesma mensagem em dois corpos distintos produz 1 linha». Nenhuma destas
e uma propriedade de uma funcao; sao propriedades de um servidor HTTP a falar
com uma fila e uma base a serio.

Tres escolhas que dao forca ao que ela prova:

1. **Correm os processos de producao.** `services/gwy/src/server.ts` e
   `services/worker-canal/src/entrada.ts`, sem uma linha de codigo de teste pelo
   meio. Um programa de ensaio que os imitasse provava-se a si proprio.
2. **A assinatura calcula-se em Python.** `hmac`/`hashlib` da biblioteca padrao,
   nao o modulo TypeScript que esta a ser testado. E uma segunda implementacao
   independente, e por isso o que se mede e **interoperabilidade** e nao
   auto-consistencia — a diferenca entre «o nosso codigo concorda consigo» e «o
   nosso codigo concorda com quem calcula HMAC-SHA256 por outro caminho».
3. **Os dominios comparam-se com tres fontes.** O `CHECK` que o PostgreSQL tem,
   o dicionario exportado (`canon/dicionario.yaml`) e a lista do modulo
   TypeScript. Duas fontes a concordar e uma copia; tres e um contrato.

O trinco e o das outras suites: a base tem de se chamar `kamba_gate8`. E ha um
segundo: sem `KAMBA_FILA_PORT` a suite **falha**, nao salta — num gate, saltar e
falhar.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

import ligacao
from tests.base import PRIVILEGIO_INSUFICIENTE, alembic_ok, em_head, exigir_base_descartavel, sqlstate
from tests_entrada import node
from tests_eventos import fila as fila_mod

sys.path.insert(0, str(node.RAIZ / "tools"))

from kamba_yaml import load_file  # noqa: E402

#: Os segredos do ensaio. Nao sao de lado nenhum: nascem nesta execucao, vao
#: para o processo pelo **ambiente** e nunca pela linha de comandos, e morrem
#: com ele. Os nomes das variaveis sao os que o `EnvSecretProvider` constroi a
#: partir de `meta_app_secret` e `meta_verify_token` (`secrets/env.ts`).
APP_SECRET_ACTUAL = f"ensaio-actual-{secrets.token_hex(8)}"
APP_SECRET_ANTERIOR = f"ensaio-anterior-{secrets.token_hex(8)}"
APP_SECRET_TERCEIRO = f"ensaio-terceiro-{secrets.token_hex(8)}"
VERIFY_TOKEN = f"ensaio-token-{secrets.token_hex(8)}"

#: Identificadores sinteticos. O `waba_id` e o `phone_number_id` sao opacos na
#: Meta e aqui tambem; o telefone usa o indicativo `999`, que a UIT nao atribui
#: a nenhum pais, pela mesma convencao de `tests_bd/apoio.ts`.
WABA = "109000000000001"
PNID = "123000000000001"
TELEFONE = "999123456789"

#: Segundos a esperar que um processo HTTP comece a responder.
#:
#: **Nao e um alvo de latencia**: e tolerancia de ambiente. Sem `node` no
#: `PATH` — o caso de uma maquina de desenvolvimento em Windows — cada arranque
#: e um `docker run` com a imagem a montar o repositorio, e a suite faz quatro
#: deles. Com 60 s, um deles estourou com o contentor **vivo** e o registo a
#: mostrar so o aviso do OpenSSL: ainda nao tinha chegado ao `service_started`.
#: O alvo de latencia do ticket (200 em < 500 ms) mede-se em
#: `db/tests_entrada_carga/`, com o processo ja a responder.
ARRANQUE = 180.0
#: Segundos a esperar que o *worker* consuma o que esta na fila.
CONSUMO = 30.0


def esperar_por(condicao, limite: float, intervalo: float = 0.2) -> bool:
    fim = time.monotonic() + limite
    while time.monotonic() < fim:
        if condicao():
            return True
        time.sleep(intervalo)
    return condicao()


def _sonda(porta: int) -> bool:
    """O `/healthz` do processo responde 200?"""
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{porta}/healthz", timeout=2
        ) as resposta:
            return resposta.status == 200
    except (urllib.error.URLError, OSError, TimeoutError):
        return False


def porta_livre() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as tomada:
        tomada.bind(("127.0.0.1", 0))
        return int(tomada.getsockname()[1])


def assinar(corpo: bytes, segredo: str) -> str:
    """O cabecalho que a Meta mandaria. **Implementacao independente da testada.**"""
    resumo = hmac.new(segredo.encode("utf-8"), corpo, hashlib.sha256).hexdigest()
    return f"sha256={resumo}"


def corpo_de_mensagem(wamid: str, *, espacos: bool = False, texto: str | None = None) -> bytes:
    """Um corpo de webhook com uma mensagem de texto, como o `E1` §5 o descreve."""
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": WABA,
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": TELEFONE,
                                "phone_number_id": PNID,
                            },
                            "contacts": [
                                {"profile": {"name": "Cliente de Ensaio"}, "wa_id": TELEFONE}
                            ],
                            "messages": [
                                {
                                    "from": TELEFONE,
                                    "id": wamid,
                                    "timestamp": "1700000000",
                                    "type": "text",
                                    "text": {"body": texto or "mensagem de ensaio"},
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }
    # `espacos=True` da o **mesmo** JSON com outros bytes: e o que o criterio 2
    # manda recusar com a assinatura do original, e o que faz dois corpos com a
    # mesma mensagem terem `jobId` diferente (criterio 4, segundo nivel).
    if espacos:
        return json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def corpo_de_estados(wamid: str, estados: tuple[str, ...]) -> bytes:
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": WABA,
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"phone_number_id": PNID},
                            "statuses": [
                                {"id": wamid, "status": estado, "recipient_id": TELEFONE}
                                for estado in estados
                            ],
                        },
                    }
                ],
            }
        ],
    }
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


class ComEntrada(unittest.TestCase):
    """PostgreSQL e fila prontos, o GWY e o *worker* a correr, tudo limpo entre testes."""

    @classmethod
    def setUpClass(cls) -> None:
        exigir_base_descartavel()
        if not os.environ.get("KAMBA_FILA_PORT", "").isdigit():
            raise AssertionError(
                "KAMBA_FILA_PORT nao esta definida: a suite de entrada precisa de uma "
                "fila real. Corra `python db/gate_bd.py --suite tests_entrada`."
            )
        import bootstrap

        bootstrap.aplicar()
        if not em_head():
            alembic_ok("upgrade", "head")
        cls._admin = ligacao.ligar("admin")
        cls._admin.autocommit = True
        cls._arrancar_processos()

    @classmethod
    def tearDownClass(cls) -> None:
        for processo in getattr(cls, "processos", []):
            processo.parar()
        cls._admin.close()

    #: Que processos esta classe precisa. Subclasses redefinem.
    #:
    #: **Por classe e nao por teste**, e a razao e medida: cada arranque e um
    #: `docker run` de uns vinte segundos, e com um por metodo a suite levava
    #: 763 s. Os dois processos nao tem estado proprio — o estado esta na base
    #: e na fila, e essas limpam-se entre testes —, pelo que partilha-los nao
    #: acopla teste nenhum. O unico que mexe no ambiente partilhado e o da fila
    #: parada, e esse para-a e volta a arranca-la de proposito: com o GWY
    #: partilhado, ele prova tambem que o **mesmo** processo volta a aceitar
    #: sem ser reiniciado, que e o que o `retryStrategy` da ligacao garante.
    PROCESSOS: tuple[str, ...] = ()

    @classmethod
    def _arrancar_processos(cls) -> None:
        cls.processos = []
        if "gwy" in cls.PROCESSOS:
            cls.gwy = cls._lancar_gwy()
        if "worker" in cls.PROCESSOS:
            cls.worker = cls._lancar_worker()

    def setUp(self) -> None:
        self.cursor = self._admin.cursor()
        self.fila = fila_mod.Fila()
        self.fila.ligar()
        self.addCleanup(self.fila.fechar)
        self.fila.limpar()
        self._limpar()
        self.addCleanup(self._limpar)

    def _limpar(self) -> None:
        for tabela in ("inbound_events", "unrouted_events"):
            self.cursor.execute(f"DELETE FROM platform.{tabela}")

    # --- os dois processos -------------------------------------------------

    @classmethod
    def _lancar_gwy(cls) -> node.Processo:
        porta = porta_livre()
        # Duas portas: a publica so leva o `/wa/webhook`, e o `/metrics` vive
        # na interna. E a correccao de um achado da revisao adversarial —
        # `inbound_queue_depth` na porta publica e o atraso da plataforma ao
        # alcance de quem alcanca a Internet.
        porta_das_metricas = porta_livre()
        processo = node.lancar(
            "services/gwy",
            "src/server.ts",
            {
                "KAMBA_QUEUE_URL": node.url_da_fila(),
                "KAMBA_AMBIENTE": "dev",
                "KAMBA_SECRET_META_APP_SECRET": APP_SECRET_ACTUAL,
                "KAMBA_SECRET_META_APP_SECRET_ANTERIOR": APP_SECRET_ANTERIOR,
                "KAMBA_SECRET_META_VERIFY_TOKEN": VERIFY_TOKEN,
                "PORT": str(porta),
                "GWY_METRICS_PORT": str(porta_das_metricas),
                "HOST": "127.0.0.1",
            },
            "gwy",
            porta=porta,
            porta_das_metricas=porta_das_metricas,
        )
        cls.processos.append(processo)
        if not esperar_por(lambda: _sonda(porta), ARRANQUE):
            raise AssertionError(f"o gwy nao comecou a responder{processo.diagnostico()}")
        return processo

    @classmethod
    def _lancar_worker(cls) -> node.Processo:
        porta = porta_livre()
        processo = node.lancar(
            "services/worker-canal",
            "src/entrada.ts",
            {
                "KAMBA_ENTRADA_DB_URL": node.url_da_base("app"),
                # KAM-014: as duas ligacoes do CHR, e a fase. Sem elas o
                # processo **nao arranca** — e nao arranca de proposito: o
                # braco `chr` do encaminhador e agora o CHR, a guarda do
                # ADR-011 corre antes de se aceitar trabalho, e `KAMBA_FASE`
                # ausente ou com outro valor nao a desliga.
                "KAMBA_CHR_RESOLVER_DB_URL": node.url_da_base("resolver"),
                "KAMBA_CHR_IDENTITY_DB_URL": node.url_da_base("identity"),
                "KAMBA_FASE": "piloto",
                "KAMBA_ENV": "dev",
                # O `EnvKeyProvider` do KAM-008 le as chaves do ambiente. Nao
                # ha identidade a resolver nesta suite — os corpos sao do
                # KAM-013 e nenhum traz um canal conhecido —, mas o processo
                # arranca o modulo, e arrancar sem chaves levanta.
                **node.chaves_de_identidade(),
                "KAMBA_QUEUE_URL": node.url_da_fila(),
                "ENTRADA_PORT": str(porta),
            },
            "entrada",
            porta=porta,
        )
        cls.processos.append(processo)
        if not esperar_por(lambda: _sonda(porta), ARRANQUE):
            raise AssertionError(
                f"o worker de entrada nao arrancou{processo.diagnostico()}"
            )
        return processo

    # --- HTTP --------------------------------------------------------------

    def post(self, corpo: bytes, assinatura: str | None, *, porta: int | None = None):
        """Devolve `(codigo, corpo)`. Um 4xx/5xx nao e excepcao: e o resultado."""
        cabecalhos = {"content-type": "application/json"}
        if assinatura is not None:
            cabecalhos["x-hub-signature-256"] = assinatura
        pedido = urllib.request.Request(
            f"http://127.0.0.1:{porta or self.gwy.porta}/wa/webhook",
            data=corpo,
            headers=cabecalhos,
            method="POST",
        )
        try:
            with urllib.request.urlopen(pedido, timeout=30) as resposta:
                return resposta.status, resposta.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as erro:
            return erro.code, erro.read().decode("utf-8", "replace")

    def get_verificacao(self, token: str, desafio: str, modo: str = "subscribe"):
        from urllib.parse import urlencode

        consulta = urlencode(
            {"hub.mode": modo, "hub.verify_token": token, "hub.challenge": desafio}
        )
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{self.gwy.porta}/wa/webhook?{consulta}", timeout=30
            ) as resposta:
                return resposta.status, resposta.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as erro:
            return erro.code, erro.read().decode("utf-8", "replace")

    # --- leituras ----------------------------------------------------------

    #: A forma de um `jobId` desta fila: `sha256` do corpo, em hexadecimais.
    #:
    #: Nao se usa o `Fila.jobs()` do `tests_eventos`, e a razao e exacta: ele
    #: filtra os sufixos de chave por **serem um UUID**, porque os `jobId` do
    #: KAM-005 sao o `event_id` (UUIDv7). Os desta fila sao o resumo do corpo, e
    #: o filtro deixava-os todos de fora — a primeira execucao desta suite leu
    #: «0 jobs» com a fila cheia.
    FORMA_DO_JOB_ID = re.compile(r"^[0-9a-f]{64}$")

    def jobs_na_fila(self, fila: str = "wa-inbound") -> set[str]:
        prefixo = f"bull:{fila}:"
        return {
            chave[len(prefixo) :]
            for chave in self.fila.chaves(f"{prefixo}*")
            if self.FORMA_DO_JOB_ID.match(chave[len(prefixo) :])
        }

    def linhas(self, tabela: str) -> list[tuple]:
        self.cursor.execute(
            f"SELECT kind, event_key FROM platform.{tabela} ORDER BY kind, event_key"
        )
        return [tuple(linha) for linha in self.cursor.fetchall()]

    def contar(self, tabela: str) -> int:
        self.cursor.execute(f"SELECT count(*) FROM platform.{tabela}")
        return int(self.cursor.fetchone()[0])


class TestVerificacao(ComEntrada):
    """Criterio 1, por HTTP real."""

    PROCESSOS = ("gwy",)

    def test_o_token_certo_responde_200_com_o_corpo_igual_ao_desafio(self) -> None:
        codigo, corpo = self.get_verificacao(VERIFY_TOKEN, "1158201444")
        self.assertEqual(codigo, 200)
        # Byte a byte: a Meta compara o corpo com o desafio que mandou.
        self.assertEqual(corpo, "1158201444")

    def test_o_token_errado_responde_403(self) -> None:
        for token in ("errado", "", VERIFY_TOKEN[:-1], VERIFY_TOKEN + "x"):
            with self.subTest(token=token):
                codigo, corpo = self.get_verificacao(token, "segredo-do-desafio")
                self.assertEqual(codigo, 403)
                self.assertNotIn("segredo-do-desafio", corpo)

    def test_outro_modo_responde_403(self) -> None:
        codigo, _ = self.get_verificacao(VERIFY_TOKEN, "1", modo="unsubscribe")
        self.assertEqual(codigo, 403)


class TestAssinatura(ComEntrada):
    """Criterios 2 e 3, com a assinatura calculada em Python."""

    PROCESSOS = ("gwy",)

    def test_sem_assinatura_responde_401_e_nao_enfileira(self) -> None:
        corpo = corpo_de_mensagem("wamid.SEM.ASSINATURA")
        codigo, _ = self.post(corpo, None)
        self.assertEqual(codigo, 401)
        self.assertEqual(self.jobs_na_fila(), set())

    def test_assinatura_invalida_responde_401(self) -> None:
        corpo = corpo_de_mensagem("wamid.MA.ASSINATURA")
        for assinatura in ("sha256=" + "0" * 64, "lixo", "sha256=", "sha1=" + "0" * 40):
            with self.subTest(assinatura=assinatura[:16]):
                codigo, _ = self.post(corpo, assinatura)
                self.assertEqual(codigo, 401)
        self.assertEqual(self.jobs_na_fila(), set())

    def test_o_anel_aceita_o_actual_e_o_anterior_e_recusa_um_terceiro(self) -> None:
        """Criterio 3: `[actual, anterior]`, e um terceiro segredo da 401."""
        for segredo, esperado in (
            (APP_SECRET_ACTUAL, 200),
            (APP_SECRET_ANTERIOR, 200),
            (APP_SECRET_TERCEIRO, 401),
        ):
            with self.subTest(segredo=segredo.split("-")[1]):
                corpo = corpo_de_mensagem(f"wamid.ANEL.{segredo.split('-')[1]}")
                codigo, _ = self.post(corpo, assinar(corpo, segredo))
                self.assertEqual(codigo, esperado)

    def test_o_corpo_reserializado_com_a_assinatura_do_original_da_401(self) -> None:
        """Criterio 2, a letra: a assinatura e sobre os **bytes recebidos**."""
        original = corpo_de_mensagem("wamid.RESERIALIZADO")
        espacado = corpo_de_mensagem("wamid.RESERIALIZADO", espacos=True)
        self.assertNotEqual(original, espacado)
        self.assertEqual(json.loads(original), json.loads(espacado))

        assinatura = assinar(original, APP_SECRET_ACTUAL)
        self.assertEqual(self.post(original, assinatura)[0], 200)
        self.assertEqual(self.post(espacado, assinatura)[0], 401)
        self.assertEqual(len(self.jobs_na_fila()), 1)

    def _metrica(self, nome: str) -> int:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{self.gwy.porta_das_metricas}/metrics", timeout=10
        ) as resposta:
            texto = resposta.read().decode("utf-8")
        achado = re.search(rf"^{nome} (-?\d+)$", texto, re.M)
        self.assertIsNotNone(achado, f"{nome} nao esta em /metrics: {texto}")
        return int(achado.group(1))

    def test_o_metrics_NAO_esta_na_porta_publica(self) -> None:
        """Achado da revisao adversarial, medido no processo a correr.

        O webhook e alcancavel de fora (ADR-001). Com o `/metrics` na mesma
        porta, qualquer pessoa que chegue ao GWY le `inbound_queue_depth` — o
        atraso da plataforma em tempo real — e sabe quando a fila passou os
        10 000 do descarte do criterio 7.
        """
        # **So o `/metrics`.** O `/healthz` fica na porta publica de proposito:
        # e o contrato do KAM-001 (`packages/contracts/schemas/healthz.response.v1.json`)
        # e o `make smoke` verifica-o em `gwy=3000`. E a sonda de vivacidade do
        # servico, nao observabilidade — nao diz nada sobre o estado da fila.
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{self.gwy.porta}/metrics", timeout=10
            ) as resposta:
                codigo = resposta.status
        except urllib.error.HTTPError as erro:
            codigo = erro.code
        self.assertNotEqual(codigo, 200, "/metrics nao devia responder na porta publica")

        # O `/healthz` responde, e tem de responder.
        with urllib.request.urlopen(
            f"http://127.0.0.1:{self.gwy.porta}/healthz", timeout=10
        ) as resposta:
            self.assertEqual(resposta.status, 200)

        # E o `/metrics` responde na interna.
        with urllib.request.urlopen(
            f"http://127.0.0.1:{self.gwy.porta_das_metricas}/metrics", timeout=10
        ) as resposta:
            self.assertEqual(resposta.status, 200)
            self.assertIn("inbound_queue_depth", resposta.read().decode("utf-8"))

    def test_um_corpo_grande_demais_responde_413_e_nao_enfileira(self) -> None:
        """Achado da revisao adversarial: o corpo era lido inteiro sem tecto.

        Um pedido **sem assinatura nenhuma** com um corpo acima do tecto nao
        pode fazer o processo alocar o corpo todo. Aqui mede-se pelo efeito: 413
        e nada na fila.
        """
        grande = b"{" + b" " * (1_048_576 + 1)
        codigo, _ = self.post(grande, None)
        self.assertEqual(codigo, 413)
        self.assertEqual(self.jobs_na_fila(), set())
        # E com assinatura valida tambem: o tecto e do tamanho, nao da origem.
        codigo, _ = self.post(grande, assinar(grande, APP_SECRET_ACTUAL))
        self.assertEqual(codigo, 413)
        self.assertEqual(self.jobs_na_fila(), set())

    def test_o_gwy_conta_as_falhas_de_assinatura(self) -> None:
        # O **delta**, e nao o valor: o processo e partilhado pela classe, e um
        # contador absoluto acoplava este teste a ordem dos outros.
        antes = self._metrica("gwy_sig_fail")
        corpo = corpo_de_mensagem("wamid.METRICA")
        self.post(corpo, None)
        self.post(corpo, "sha256=" + "f" * 64)
        self.assertEqual(self._metrica("gwy_sig_fail") - antes, 2)


class TestFila(ComEntrada):
    """Criterios 4 (primeiro nivel) e 5."""

    PROCESSOS = ("gwy",)

    def test_o_mesmo_corpo_duas_vezes_produz_um_job(self) -> None:
        """Criterio 4, primeiro nivel: `jobId = sha256(corpo)`, na fila a serio."""
        corpo = corpo_de_mensagem("wamid.BYTE.A.BYTE")
        assinatura = assinar(corpo, APP_SECRET_ACTUAL)
        self.assertEqual(self.post(corpo, assinatura)[0], 200)
        self.assertEqual(self.post(corpo, assinatura)[0], 200)
        jobs = self.jobs_na_fila()
        self.assertEqual(len(jobs), 1, f"ficaram {len(jobs)} jobs para o mesmo corpo")
        self.assertEqual(jobs, {hashlib.sha256(corpo).hexdigest()})

    def test_corpos_diferentes_produzem_jobs_diferentes(self) -> None:
        for sufixo in ("A", "B", "C"):
            corpo = corpo_de_mensagem(f"wamid.{sufixo}")
            self.assertEqual(self.post(corpo, assinar(corpo, APP_SECRET_ACTUAL))[0], 200)
        self.assertEqual(len(self.jobs_na_fila()), 3)

    def test_o_200_sai_com_o_job_ja_na_fila(self) -> None:
        """Criterio 5: quando a resposta chega, o *job* **esta** na fila."""
        corpo = corpo_de_mensagem("wamid.DEPOIS.DE.ENFILEIRAR")
        codigo, _ = self.post(corpo, assinar(corpo, APP_SECRET_ACTUAL))
        self.assertEqual(codigo, 200)
        # Sem espera nenhuma: a leitura e imediatamente depois da resposta.
        self.assertEqual(self.jobs_na_fila(), {hashlib.sha256(corpo).hexdigest()})

    def test_com_a_fila_parada_responde_503_e_nunca_200(self) -> None:
        """Criterio 5, a segunda metade: 503 para a Meta repetir, nunca 200."""
        contentor = os.environ.get("KAMBA_GATE_FILA", "")
        self.assertTrue(contentor, "KAMBA_GATE_FILA nao esta definida")

        def docker(*argumentos: str) -> None:
            resultado = subprocess.run(
                ["docker", *argumentos, contentor], capture_output=True, text=True
            )
            if resultado.returncode != 0:
                raise AssertionError(f"docker {argumentos[0]}: {resultado.stderr[-300:]}")

        docker("stop", "--timeout", "0")
        self.addCleanup(lambda: docker("start"))
        try:
            codigos = set()
            for i in range(5):
                corpo = corpo_de_mensagem(f"wamid.FILA.PARADA.{i}")
                codigo, texto = self.post(corpo, assinar(corpo, APP_SECRET_ACTUAL))
                codigos.add(codigo)
                # Nem a mensagem de erro do cliente da fila sai na resposta.
                self.assertNotIn("ECONNREFUSED", texto)
                self.assertNotIn("redis", texto.lower())
            self.assertEqual(
                codigos,
                {503},
                f"com a fila parada responderam-se {sorted(codigos)}{self.gwy.diagnostico()}",
            )
        finally:
            docker("start")
        self.assertTrue(self.fila.esperar_viva(60), "a fila nao voltou")

        # E com a fila de volta, o GWY volta a aceitar **sem ser reiniciado**:
        # e o que o `retryStrategy` da ligacao garante.
        corpo = corpo_de_mensagem("wamid.DEPOIS.DE.VOLTAR")
        self.assertTrue(
            esperar_por(
                lambda: self.post(corpo, assinar(corpo, APP_SECRET_ACTUAL))[0] == 200,
                60.0,
                intervalo=1.0,
            ),
            f"o gwy nao voltou a aceitar{self.gwy.diagnostico()}",
        )


class TestRegistoEQuarentena(ComEntrada):
    """Criterios 4 (segundo nivel), 6 e 8, com o *worker* a consumir."""

    PROCESSOS = ("gwy", "worker")

    def enviar(self, corpo: bytes) -> None:
        codigo, _ = self.post(corpo, assinar(corpo, APP_SECRET_ACTUAL))
        self.assertEqual(codigo, 200)

    def esperar_linhas(self, tabela: str, quantas: int) -> None:
        self.assertTrue(
            esperar_por(lambda: self.contar(tabela) >= quantas, CONSUMO),
            f"{tabela} ficou com {self.contar(tabela)} de {quantas} linha(s)"
            f"{self.worker.diagnostico()}",
        )

    def test_a_mesma_mensagem_em_dois_corpos_distintos_da_uma_linha(self) -> None:
        """Criterio 4, segundo nivel: `UNIQUE (kind, event_key)`.

        Os dois corpos tem o **mesmo** `wamid` e bytes diferentes, pelo que o
        `jobId` nao os junta: sao dois *jobs*. E o indice unico que os junta.
        """
        compacto = corpo_de_mensagem("wamid.SEMANTICO")
        espacado = corpo_de_mensagem("wamid.SEMANTICO", espacos=True)
        self.assertNotEqual(
            hashlib.sha256(compacto).hexdigest(), hashlib.sha256(espacado).hexdigest()
        )
        self.enviar(compacto)
        self.enviar(espacado)
        self.esperar_linhas("inbound_events", 1)
        # Dois *jobs* distintos entraram na fila, e **uma** linha ficou.
        self.assertEqual(len(self.jobs_na_fila()), 2)
        time.sleep(2.0)
        self.assertEqual(self.linhas("inbound_events"), [("message", "wamid.SEMANTICO")])

    def test_tres_estados_do_mesmo_wamid_dao_tres_linhas(self) -> None:
        """`event_key` de estados e `wamid:estado` — a letra do criterio 4."""
        self.enviar(corpo_de_estados("wamid.ESTADOS", ("sent", "delivered", "read")))
        self.esperar_linhas("inbound_events", 3)
        self.assertEqual(
            self.linhas("inbound_events"),
            [
                ("statuses", "wamid.ESTADOS:delivered"),
                ("statuses", "wamid.ESTADOS:read"),
                ("statuses", "wamid.ESTADOS:sent"),
            ],
        )

    def test_json_invalido_da_200_e_quarentena_e_nunca_5xx(self) -> None:
        """Criterio 6, a letra: 200 e quarentena; nunca 5xx, para nao haver *retry storm*."""
        corpo = b'{"entry": [isto nao e json'
        codigo, _ = self.post(corpo, assinar(corpo, APP_SECRET_ACTUAL))
        self.assertEqual(codigo, 200)
        self.esperar_linhas("unrouted_events", 1)
        self.cursor.execute(
            "SELECT kind, motivo, event_key, waba_id, payload IS NOT NULL "
            "FROM platform.unrouted_events"
        )
        linha = tuple(self.cursor.fetchone())
        self.assertEqual(linha[0], "invalido")
        self.assertEqual(linha[1], "json_invalido")
        # A chave e deterministica: a re-entrega do mesmo corpo mau nao cria
        # uma segunda linha.
        self.assertEqual(linha[2], "k_" + hashlib.sha256(corpo).hexdigest()[:32])
        self.assertIsNone(linha[3], "a quarentena de um corpo ilegivel nao tem waba_id")
        self.assertTrue(linha[4], "o corpo bruto nao foi guardado para diagnostico")
        self.assertEqual(self.contar("inbound_events"), 0)

    def test_um_campo_desconhecido_vai_a_quarentena_e_nao_ao_registo(self) -> None:
        corpo = json.dumps(
            {
                "entry": [
                    {
                        "id": WABA,
                        "changes": [
                            {
                                "field": "campo_que_alguem_subscreveu",
                                "value": {"metadata": {"phone_number_id": PNID}},
                            }
                        ],
                    }
                ]
            },
            separators=(",", ":"),
        ).encode("utf-8")
        self.enviar(corpo)
        self.esperar_linhas("unrouted_events", 1)
        self.cursor.execute("SELECT kind, motivo, waba_id FROM platform.unrouted_events")
        self.assertEqual(tuple(self.cursor.fetchone()), ("desconhecido", "campo_desconhecido", WABA))
        self.assertEqual(self.contar("inbound_events"), 0)

    def test_os_onze_campos_de_webhook_registam_se_com_o_kind_certo(self) -> None:
        """Criterio 8: o `kind` de cada campo, e os doze que `inbound_events` aceita."""
        campos = {
            "smb_message_echoes": "echo",
            "history": "history",
            "smb_app_state_sync": "smb_app_state_sync",
            "account_update": "account_update",
            "phone_number_quality_update": "phone_number_quality_update",
            "business_capability_update": "business_capability_update",
            "account_alerts": "account_alerts",
            "message_template_status_update": "message_template_status_update",
            "template_category_update": "template_category_update",
            "message_template_quality_update": "message_template_quality_update",
        }
        for campo in campos:
            corpo = json.dumps(
                {
                    "entry": [
                        {
                            "id": WABA,
                            "changes": [
                                {
                                    "field": campo,
                                    "value": {
                                        "metadata": {"phone_number_id": PNID},
                                        "ensaio": campo,
                                    },
                                }
                            ],
                        }
                    ]
                },
                separators=(",", ":"),
            ).encode("utf-8")
            self.enviar(corpo)
        self.esperar_linhas("inbound_events", len(campos))
        self.cursor.execute("SELECT DISTINCT kind FROM platform.inbound_events")
        self.assertEqual(
            {linha[0] for linha in self.cursor.fetchall()}, set(campos.values())
        )
        # **Uma** linha de quarentena, e e do KAM-014: o `smb_message_echoes` da
        # um `echo`, o `echo` vai ao CHR (`DESTINO_POR_KIND`), e esta suite nao
        # semeia canal nenhum — pelo que o CHR nao resolve o `phone_number_id` e
        # po-e na quarentena com `canal_desconhecido`, que e o criterio 2 desse
        # ticket. Os outros nove campos vao a `ingestao` e a `gestao_de_canal`,
        # que continuam a ser costura e nao escrevem nada.
        #
        # Antes do KAM-014 esta contagem era **zero**, porque o braco `chr` do
        # encaminhador tambem era costura. A asercao passa a nomear o motivo em
        # vez de contar: um zero aqui, depois do CHR ligado, significava que o
        # `echo` deixou de chegar ao CHR.
        self.esperar_linhas("unrouted_events", 1)
        self.cursor.execute("SELECT kind, motivo FROM platform.unrouted_events")
        self.assertEqual(
            [tuple(linha) for linha in self.cursor.fetchall()],
            [("desconhecido", "canal_desconhecido")],
        )

    def test_o_evento_fica_marcado_como_encaminhado(self) -> None:
        """A coluna que fecha a janela entre registar e encaminhar."""
        self.enviar(corpo_de_mensagem("wamid.PROCESSADO"))
        self.esperar_linhas("inbound_events", 1)
        self.assertTrue(
            esperar_por(
                lambda: self._processados() == 1,
                CONSUMO,
            ),
            f"`processado_at` ficou nulo{self.worker.diagnostico()}",
        )

    def _processados(self) -> int:
        self.cursor.execute(
            "SELECT count(*) FROM platform.inbound_events WHERE processado_at IS NOT NULL"
        )
        return int(self.cursor.fetchone()[0])

    def test_nenhum_dos_dois_processos_registra_telefone_nem_conteudo(self) -> None:
        """Criterio 9, de ponta a ponta: os registos dos dois processos.

        O canario vai no `from`, no `wa_id`, no `display_phone_number`, no nome
        do perfil e no corpo da mensagem — os cinco sitios por onde um telefone
        ou texto de conversa poderiam escapar.
        """
        canario_texto = "queria duas pizzas e a conta"
        self.enviar(corpo_de_mensagem("wamid.CANARIO", texto=canario_texto))
        self.esperar_linhas("inbound_events", 1)
        time.sleep(2.0)

        permitidos = {
            "ts", "level", "svc", "msg_id", "wa_type", "latency_ms", "outcome", "error_code",
        }
        for processo in (self.gwy, self.worker):
            with self.subTest(processo=processo.registo.stem):
                texto = processo.texto()
                for canario in (TELEFONE, canario_texto, "pizzas", "Cliente de Ensaio"):
                    self.assertNotIn(canario, texto, f"{canario} saiu no registo")
                # O `wamid` tambem nao: leva o numero do interlocutor em base64.
                self.assertNotIn("wamid.CANARIO", texto)
                linhas = processo.linhas()
                self.assertTrue(linhas, f"o processo nao registou nada{processo.diagnostico()}")
                for linha in linhas:
                    for chave in linha:
                        self.assertIn(chave, permitidos, f"{chave} fora dos oito do criterio 9")
                    # A regra dos digitos e a **do logger**, e nao uma mais
                    # severa inventada aqui: o tecto de seis digitos aplica-se
                    # aos campos validados como identificador livre (`wa_type`,
                    # `outcome`, `error_code`), porque e nesses que um telefone
                    # ou um NIF cabem. O `msg_id` tem forma **fechada** — `m_`
                    # mais 32 hexadecimais — e tem naturalmente uma vintena de
                    # digitos; exigir-lhe seis era exigir que o `idOpaco`
                    # deixasse de ser um resumo. A primeira versao deste teste
                    # fazia-o, e falhou com `m_918cfe…: tem 20 digitos`.
                    for chave in ("wa_type", "outcome", "error_code"):
                        valor = linha.get(chave)
                        if valor is None:
                            continue
                        digitos = sum(1 for c in str(valor) if c.isdigit())
                        self.assertLessEqual(
                            digitos, 6, f"{chave}={valor} tem {digitos} digitos"
                        )
                    if "msg_id" in linha:
                        self.assertRegex(str(linha["msg_id"]), r"^m_[0-9a-f]{32}$")


class TestEsquema(ComEntrada):
    """Os dominios e os privilegios da revisao `0008`, contra o catalogo real."""

    def dominio_do_check(self, tabela: str, restricao: str) -> set[str]:
        self.cursor.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conname = %s AND conrelid = %s::regclass",
            (restricao, f"platform.{tabela}"),
        )
        linha = self.cursor.fetchone()
        self.assertIsNotNone(linha, f"{restricao} nao existe em {tabela}")
        return set(re.findall(r"'([^']+)'", linha[0]))

    def do_dicionario(self, coluna: str) -> set[str]:
        dicionario = load_file(node.RAIZ / "canon" / "dicionario.yaml")
        for item in dicionario["dominios"]:
            if item["coluna"] == coluna:
                return set(item["valores"])
        raise AssertionError(f"{coluna} nao tem dominio em canon/dicionario.yaml")

    def do_modulo(self, nome: str) -> set[str]:
        """A lista do modulo TypeScript, lida do ficheiro.

        Le-se o **ficheiro** e nao se reescreve a lista aqui: uma copia em
        Python provava que a copia esta certa.
        """
        fonte = (
            node.RAIZ / "packages" / "core-ts" / "src" / "entrada" / "contrato.ts"
        ).read_text(encoding="utf-8")
        achado = re.search(rf"export const {nome} = \[(.*?)\] as const;", fonte, re.S)
        self.assertIsNotNone(achado, f"{nome} nao esta em contrato.ts")
        return set(re.findall(r'"([^"]+)"', achado.group(1)))

    def test_o_dominio_de_kind_e_o_mesmo_nas_tres_fontes(self) -> None:
        """O `CHECK`, o dicionario e o modulo. Duas e uma copia; tres e um contrato."""
        for tabela, coluna, constante in (
            ("inbound_events", "inbound_events.kind", "KINDS_DE_ENTRADA"),
            ("unrouted_events", "unrouted_events.kind", "KINDS_DE_QUARENTENA"),
        ):
            with self.subTest(tabela=tabela):
                do_check = self.dominio_do_check(tabela, f"{tabela}_kind_ck")
                self.assertEqual(do_check, self.do_dicionario(coluna))
                self.assertEqual(do_check, self.do_modulo(constante))

    def test_a_entrada_tem_doze_kinds_e_a_quarentena_dois(self) -> None:
        """Uma `message` na quarentena e um `invalido` no registo sao impossiveis."""
        entrada = self.dominio_do_check("inbound_events", "inbound_events_kind_ck")
        quarentena = self.dominio_do_check("unrouted_events", "unrouted_events_kind_ck")
        self.assertEqual(len(entrada), 12)
        self.assertEqual(quarentena, {"desconhecido", "invalido"})
        self.assertEqual(entrada & quarentena, set())

    def test_o_dominio_de_motivo_e_o_mesmo_nas_tres_fontes(self) -> None:
        do_check = self.dominio_do_check("unrouted_events", "unrouted_events_motivo_ck")
        self.assertEqual(do_check, self.do_dicionario("unrouted_events.motivo"))
        self.assertEqual(do_check, self.do_modulo("MOTIVOS"))

    def test_o_unique_e_por_kind_e_event_key(self) -> None:
        for tabela in ("inbound_events", "unrouted_events"):
            with self.subTest(tabela=tabela):
                self.cursor.execute(
                    "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE conname = %s AND conrelid = %s::regclass",
                    (f"{tabela}_kind_event_key_uq", f"platform.{tabela}"),
                )
                self.assertEqual(
                    self.cursor.fetchone()[0], "UNIQUE (kind, event_key)"
                )

    def test_nenhuma_das_duas_tem_tenant_id_nem_rls(self) -> None:
        """O tenant so nasce no CHR (KAM-014): sem coluna, o X-05 nao as ve."""
        for tabela in ("inbound_events", "unrouted_events"):
            with self.subTest(tabela=tabela):
                self.cursor.execute(
                    "SELECT count(*) FROM information_schema.columns "
                    "WHERE table_schema = 'platform' AND table_name = %s "
                    "AND column_name = 'tenant_id'",
                    (tabela,),
                )
                self.assertEqual(int(self.cursor.fetchone()[0]), 0)
                self.cursor.execute(
                    "SELECT relrowsecurity FROM pg_class "
                    "WHERE oid = %s::regclass",
                    (f"platform.{tabela}",),
                )
                self.assertFalse(self.cursor.fetchone()[0])

    def test_nao_ha_excepcao_de_rls_declarada_para_estas_duas(self) -> None:
        """Uma excepcao a mais e uma porta aberta que ninguem usa."""
        excepcoes = load_file(node.RAIZ / "ci" / "rls_exceptions.yaml")["excepcoes"]
        tabelas = {entrada["tabela"] for entrada in excepcoes}
        self.assertNotIn("platform.inbound_events", tabelas)
        self.assertNotIn("platform.unrouted_events", tabelas)


class TestPrivilegios(ComEntrada):
    """O que `kamba_app` consegue e nao consegue, medido pelo efeito."""

    def setUp(self) -> None:
        super().setUp()
        self.app = ligacao.ligar("app")
        self.addCleanup(self.app.close)
        self.cursor_app = self.app.cursor()

    def erro(self, sql: str, parametros: tuple = ()) -> str:
        import pg8000.dbapi

        self.cursor_app.execute("SAVEPOINT caso")
        try:
            with self.assertRaises(pg8000.dbapi.DatabaseError) as capturado:
                self.cursor_app.execute(sql, parametros)
        finally:
            self.cursor_app.execute("ROLLBACK TO SAVEPOINT caso")
        return sqlstate(capturado.exception)

    def test_a_app_registra_um_evento_e_le_o_id_de_volta(self) -> None:
        """O `RETURNING id` e a razao de haver `SELECT`: sem ele, nao ha dedup."""
        self.cursor_app.execute(
            "INSERT INTO platform.inbound_events (kind, event_key, waba_id, phone_number_id) "
            "VALUES ('message', 'wamid.PRIV', %s, %s) "
            "ON CONFLICT (kind, event_key) DO NOTHING RETURNING id",
            (WABA, PNID),
        )
        self.assertEqual(len(self.cursor_app.fetchall()), 1)
        # E a segunda vez nao devolve nada: e assim que o duplicado se conhece.
        self.cursor_app.execute(
            "INSERT INTO platform.inbound_events (kind, event_key, waba_id) "
            "VALUES ('message', 'wamid.PRIV', %s) "
            "ON CONFLICT (kind, event_key) DO NOTHING RETURNING id",
            (WABA,),
        )
        # `list(...)`: o `pg8000` devolve um tuplo vazio, nao uma lista.
        self.assertEqual(list(self.cursor_app.fetchall()), [])
        self.app.rollback()

    def test_a_app_so_actualiza_processado_at(self) -> None:
        self.cursor_app.execute(
            "INSERT INTO platform.inbound_events (kind, event_key, waba_id) "
            "VALUES ('message', 'wamid.UPD', %s) RETURNING id",
            (WABA,),
        )
        identificador = self.cursor_app.fetchone()[0]
        self.cursor_app.execute(
            "UPDATE platform.inbound_events SET processado_at = now() WHERE id = %s",
            (identificador,),
        )
        for coluna, valor in (("kind", "'echo'"), ("event_key", "'outra'"), ("waba_id", "'x'")):
            with self.subTest(coluna=coluna):
                self.assertEqual(
                    self.erro(
                        f"UPDATE platform.inbound_events SET {coluna} = {valor} WHERE id = %s",
                        (identificador,),
                    ),
                    PRIVILEGIO_INSUFICIENTE,
                )
        self.app.rollback()

    def test_a_app_poe_em_quarentena_com_ON_CONFLICT(self) -> None:
        """O `ON CONFLICT` exige `SELECT` nas colunas de inferencia.

        Foi esta a forma do defeito: a insercao simples passava, a do
        `SQL_QUARENTENA` falhava com 42501, e o *worker* nao registava nada —
        a quarentena ficava a zero e parecia que o corpo nunca chegara.
        """
        for _ in range(2):
            self.cursor_app.execute(
                "INSERT INTO platform.unrouted_events "
                "(kind, event_key, motivo, payload) VALUES "
                "('invalido', 'k_conflito', 'json_invalido', 'YWJj') "
                "ON CONFLICT (kind, event_key) DO NOTHING"
            )
        # A leitura e pela **mesma** ligacao: a do papel da aplicacao nunca
        # confirma, e o administrador nao ve o que ela ainda nao confirmou. E
        # de duas colunas — as de inferencia — porque `count(*)` pede `SELECT`
        # de tabela, que este papel nao tem (o teste seguinte prova-o).
        self.cursor_app.execute(
            "SELECT kind, event_key FROM platform.unrouted_events "
            "WHERE event_key = 'k_conflito'"
        )
        self.assertEqual(
            [tuple(linha) for linha in self.cursor_app.fetchall()],
            [("invalido", "k_conflito")],
            "duas insercoes com a mesma chave deviam deixar uma linha",
        )
        self.app.rollback()

    def test_a_app_escreve_na_quarentena_e_NAO_le_o_payload(self) -> None:
        """A coluna `payload` guarda corpo de conversa: quem escreve nao le.

        **O que `kamba_app` ganhou com o `SELECT (kind, event_key)` esta medido
        aqui, e nao e nada.** Conceder duas colunas tornou `count(*)` possivel —
        o PostgreSQL aceita-o com privilegio em **qualquer** coluna —, e isso
        esta declarado em vez de escondido: a objeccao que levou o `events_dlq`
        (KAM-006) a nao ter `SELECT` era «um `id` sequencial mede o volume do
        vizinho», e aqui nao ha vizinho. A quarentena nao tem `tenant_id`, o
        `id` e `gen_random_uuid()`, e a contagem e da plataforma inteira: diz
        quantos corpos nao encaixaram, nao de quem sao.

        O que continua fechado e o que importa: o `payload`, que pode levar
        telefone e texto de mensagem, e o `motivo`.
        """
        self.cursor_app.execute(
            "INSERT INTO platform.unrouted_events "
            "(kind, event_key, motivo, payload) VALUES "
            "('invalido', 'k_ensaio', 'json_invalido', 'YWJj')"
        )
        for coluna in ("payload", "motivo", "waba_id", "phone_number_id", "recebido_at"):
            with self.subTest(coluna=coluna):
                self.assertEqual(
                    self.erro(f"SELECT {coluna} FROM platform.unrouted_events"),
                    PRIVILEGIO_INSUFICIENTE,
                )
        # E nenhum `UPDATE`: quem tria uma quarentena e quem opera.
        self.assertEqual(
            self.erro(
                "UPDATE platform.unrouted_events SET processado_at = now() "
                "WHERE event_key = 'k_ensaio'"
            ),
            PRIVILEGIO_INSUFICIENTE,
        )
        # O que **passa**, e esta dito na docstring: as duas colunas de
        # inferencia e, com elas, a contagem da plataforma inteira.
        self.cursor_app.execute("SELECT count(*) FROM platform.unrouted_events")
        self.assertGreaterEqual(int(self.cursor_app.fetchone()[0]), 1)
        self.app.rollback()

    def test_a_app_nao_apaga_de_nenhuma_das_duas(self) -> None:
        for tabela in ("inbound_events", "unrouted_events"):
            with self.subTest(tabela=tabela):
                self.assertEqual(
                    self.erro(f"DELETE FROM platform.{tabela}"), PRIVILEGIO_INSUFICIENTE
                )

    def test_o_check_do_kind_recusa_um_valor_fora_do_dominio(self) -> None:
        from tests.base import VIOLACAO_DE_CHECK

        self.assertEqual(
            self.erro(
                "INSERT INTO platform.inbound_events (kind, event_key, waba_id) "
                "VALUES ('invalido', 'k_x', %s)",
                (WABA,),
            ),
            VIOLACAO_DE_CHECK,
            "um `invalido` entrou no registo de entrada",
        )
        self.assertEqual(
            self.erro(
                "INSERT INTO platform.unrouted_events (kind, event_key, motivo) "
                "VALUES ('message', 'wamid.x', 'json_invalido')"
            ),
            VIOLACAO_DE_CHECK,
            "uma `message` entrou na quarentena",
        )

    def test_o_check_do_payload_tem_tecto(self) -> None:
        from tests.base import VIOLACAO_DE_CHECK

        # O tecto esta no `CHECK` **e** no codigo: aqui prova-se o do `CHECK`,
        # e `entrada.registo.test.ts` prova que o codigo nao chega a viola-lo.
        self.assertEqual(
            self.erro(
                "INSERT INTO platform.unrouted_events (kind, event_key, motivo, payload) "
                "VALUES ('invalido', 'k_grande', 'json_invalido', %s)",
                ("a" * 262_145,),
            ),
            VIOLACAO_DE_CHECK,
        )


if __name__ == "__main__":
    unittest.main()
