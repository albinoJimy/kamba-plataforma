"""A porta do *screening* no `submit_quote` (KAM-228, KAM-230).

O KAM-222 entregou a ponte (`ScreeningPeloCom`, `test_screening_pelo_com.py`) e o
`conferir_condicoes` que a chama (`test_orcamento.py`). Aqui mede-se a
**montagem**: o executor do `submit_quote` passa a porta ao `responder`, pela
ToolLayer, e o `screen` corre numa *thread*.

## O COM e o AGR destes ensaios

O COM e um servidor HTTP de ensaio em `127.0.0.1`, numa *thread*, que fala o
contrato da rota `POST /internal/screen` (o corpo de `ScreeningPeloCom`, a
resposta `{"tipo": "ok", "valor": ...}`). O transporte e o real
(`_transporte_httpx`): os cabecalhos, o *timeout* e a ligacao recusada sao os de
producao. O `screen` real do COM — a politica, as regras, a gravacao — e medido
em `services/com/tests/screening.test.ts` e `api.interna.test.ts`; o AGR contra
o COM TypeScript a correr e do credor **KAM-230**.

**O classificador do COM chama o AGR, e o AGR destes ensaios e o ciclo de
eventos do proprio ensaio** (`asyncio.start_server`). E a topologia que o
criterio 1 descreve: o AGR espera o COM, e o COM espera o `/internal/screening`
do mesmo AGR. Se o executor corresse no ciclo, o COM nao tinha quem lhe
respondesse, e as condicoes recusavam. O canario
(`test_com_o_ciclo_preso_as_condicoes_recusam`) corre o executor no ciclo e
exige a recusa **e** que o COM tenha chamado o AGR, chegando tarde: um COM de
ensaio que nao chamasse ninguem deixava o canario vermelho (achado 4 da revisao
adversarial, medido por mutacao).

## A finalidade das condicoes (decisao B do fundador, 2026-11-20; KAM-230)

As condicoes tem finalidade de transferencia propria, a
`classificacao_de_condicoes`. O `TestAFinalidade` mede-a a sair do AGR no corpo
do COM e a chegar ao classificador pelo COM de ensaio; o *gate* de destino que
a consulta e o `test_llm_screening.py`, e os dois processos juntos, com a base,
o `db/tests_entrada/test_screen_com.py`.

## O prazo e a tomada (achados 2, 3 e 9 da revisao do KAM-228; KAM-230)

O `TestOPrazo` mede o prazo absoluto que a ToolLayer da ao executor, e o
`TestATomada` mede o `screen` a correr sem a tomada: com uma so tomada, outra
invocacao corre enquanto o COM responde devagar.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import datetime
import http.server
import io
import json
import logging
import os
import socket
import threading
import time
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from kamba_agr import __main__ as arranque
from kamba_agr.orcamento import regras
from kamba_agr.tls import orcamento as rep
from kamba_agr.tls import orcamento_tools
from kamba_agr.tls import screening as ponte
from kamba_agr.tls.camada import VARIAVEL_DE_TIMEOUT_ESCRITA, ToolLayer
from kamba_agr.tls.catalogo import catalogo_do_piloto
from kamba_agr.tls.com import CABECALHO_INTERNO, CABECALHO_TENANT, ClienteDoCom
from kamba_agr.tls.erros import VALIDATION_ERROR
from kamba_agr.tls.especificacoes import Catalogo, ErroDeBackend, Pedido
from kamba_core.destinos import FINALIDADE_CLASSIFICACAO, FINALIDADE_CONDICOES, FINALIDADES
from test_tls import TENANT, _Ligacao, contexto
from test_vendedor import LOJA

AGORA = datetime.datetime(2026, 11, 19, 12, 0, tzinfo=datetime.UTC)
QID = "6f1d2c3b-4a59-4e6f-8a7b-9c0d1e2f3a4b"
REFERENCIA = regras.referencia_interna(QID)
CREDENCIAL = "credencial-de-ensaio"
LIMPAS = "entrega combinada consigo"
#: Um texto que a guarda do KAM-033 deixa passar e que o COM de ensaio bloqueia,
#: para que a recusa venha do `screen` e nao da guarda.
BLOQUEADAS = "entrega com brinde da casa"
#: O tecto do classificador no COM de ensaio. Curto, para o canario nao demorar.
TECTO_DO_CLASSIFICADOR_S = 1.0

RAIZ = Path(__file__).resolve().parents[3]


# ------------------------------------------------------------------ o AGR


class _AgrNoCiclo:
    """O `/internal/screening` do AGR, servido pelo ciclo de eventos do ensaio."""

    def __init__(self) -> None:
        self.chamadas = 0
        #: Os corpos lidos, pela ordem (KAM-230: a finalidade que chegou).
        self.corpos: list[dict[str, Any]] = []
        #: As ligacoes aceites, contadas a entrada: uma que chegue tarde, ja
        #: abandonada pelo COM, conta aqui e nao em `chamadas`.
        self.ligacoes = 0
        self.url = ""
        self._servidor: asyncio.base_events.Server | None = None

    async def __aenter__(self) -> "_AgrNoCiclo":
        self._servidor = await asyncio.start_server(self._atender, "127.0.0.1", 0)
        porta = self._servidor.sockets[0].getsockname()[1]
        self.url = f"http://127.0.0.1:{porta}/internal/screening"
        return self

    async def __aexit__(self, *_: object) -> None:
        assert self._servidor is not None
        self._servidor.close()
        await self._servidor.wait_closed()

    async def _atender(self, leitor: asyncio.StreamReader, escritor: asyncio.StreamWriter) -> None:
        self.ligacoes += 1
        try:
            cabecalho = await leitor.readuntil(b"\r\n\r\n")
        except (asyncio.IncompleteReadError, ConnectionError):
            escritor.close()
            return
        tamanho = 0
        for linha in cabecalho.decode("latin-1").split("\r\n"):
            nome, _, valor = linha.partition(":")
            if nome.strip().lower() == "content-length":
                tamanho = int(valor.strip())
        self.corpos.append(json.loads(await leitor.readexactly(tamanho)))
        self.chamadas += 1
        corpo = b'{"resultado":"classificado"}'
        escritor.write(
            b"HTTP/1.1 200 OK\r\ncontent-type: application/json\r\n"
            + f"content-length: {len(corpo)}\r\nconnection: close\r\n\r\n".encode()
            + corpo
        )
        await escritor.drain()
        escritor.close()


# ------------------------------------------------------------------ o COM


def _porta_livre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _ComDeEnsaio:
    """A rota `POST /internal/screen` do COM, por HTTP real, numa *thread*.

    `modo`: `normal`, `em_baixo` (503 com `UPSTREAM_DOWN`) ou `lento` (dorme
    `atraso_s` antes de responder). Em `normal`, um texto com «brinde» sai
    `bloqueada` pela regra `alcool`; o resto vai ao classificador do AGR, e so a
    resposta dele da `permitida` — sem ele, `condicional`, como no `screen` real.
    """

    def __init__(self, url_do_agr: str | None = None, modo: str = "normal", atraso_s: float = 0.0) -> None:
        self.url_do_agr = url_do_agr
        self.modo = modo
        self.atraso_s = atraso_s
        self.pedidos: list[tuple[dict[str, str], dict[str, Any]]] = []
        com = self

        class _Pedido(http.server.BaseHTTPRequestHandler):
            def log_message(self, *_: object) -> None:  # noqa: D102 — sem registo
                return None

            def do_POST(self) -> None:  # noqa: N802
                corpo = json.loads(self.rfile.read(int(self.headers["content-length"])))
                com.pedidos.append(({k.lower(): v for k, v in self.headers.items()}, corpo))
                estado, resposta = com._responder(self.path, corpo)
                cru = json.dumps(resposta).encode()
                try:
                    self.send_response(estado)
                    self.send_header("content-type", "application/json")
                    self.send_header("content-length", str(len(cru)))
                    self.end_headers()
                    self.wfile.write(cru)
                except OSError:
                    # O AGR ja desistiu por tempo e fechou a ligacao.
                    pass

        self._servidor = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Pedido)
        self._servidor.daemon_threads = True
        self.base = f"http://127.0.0.1:{self._servidor.server_address[1]}"
        self._fio = threading.Thread(target=self._servidor.serve_forever, daemon=True)

    def __enter__(self) -> "_ComDeEnsaio":
        self._fio.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._servidor.shutdown()
        self._servidor.server_close()

    def _classificador_respondeu(self, corpo: dict[str, Any]) -> bool:
        if self.url_do_agr is None:
            return False
        import urllib.request

        # A finalidade e o prazo seguem para o classificador, como no COM real
        # (`operacaoDeScreen`, KAM-230).
        pedido = urllib.request.Request(
            self.url_do_agr,
            data=json.dumps(
                {"textos": corpo["textos"], "finalidade": corpo["finalidade"], "prazo_ms": corpo["prazo_ms"]}
            ).encode(),
            method="POST",
        )
        try:
            with urllib.request.urlopen(pedido, timeout=TECTO_DO_CLASSIFICADOR_S) as resposta:
                return resposta.status == 200
        except OSError:
            return False

    def _responder(self, caminho: str, corpo: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        if caminho != ponte.ROTA:
            return 404, {"tipo": "erro", "erro": "NOT_FOUND"}
        if self.modo == "em_baixo":
            return 503, {"tipo": "erro", "erro": "UPSTREAM_DOWN"}
        if self.modo == "lento":
            time.sleep(self.atraso_s)
        if any("brinde" in texto for texto in corpo["textos"]):
            valor = {"decisao": "bloqueada", "regras": ["alcool"], "confianca": 1.0}
        elif self._classificador_respondeu(corpo):
            valor = {"decisao": "permitida", "regras": ["moda"], "confianca": 0.95}
        else:
            valor = {"decisao": "condicional", "regras": ["moda", "classificador_indisponivel"], "confianca": 0}
        return 200, {"tipo": "ok", "valor": {**valor, "versao_politica": "2026.11.0"}}


# ------------------------------------------------------------------ a montagem


def _cliente(base: str) -> ClienteDoCom:
    return ClienteDoCom(base=base, credencial=lambda: CREDENCIAL)


def _gravar_sem_base(_ligacao, _tenant, _contacto, quote_id, valor_minor, validade, limpas, agora):  # noqa: ANN001, ANN202
    """O `gravar_a_resposta_do_dono` sem a base: o eco, sem escrita.

    As condicoes ja vem conferidas pelo executor (KAM-230: sem a tomada); o que
    fica de fora e so a transaccao, que e do `db/tests_agr/test_quote_requests.py`.
    """
    validade = validade or regras.validade_por_omissao(agora)
    previsao = rep.texto_da_proposta(quote_id, "SKU-300", valor_minor, validade, limpas, agora)
    return rep.Resposta(quote_id, valor_minor, validade, limpas, "a" * 8 + "-1111-4111-8111-" + "1" * 12,
                        previsao, sku="SKU-300")


class _Montagem(unittest.TestCase):
    """O `submit_quote` ligado como o `__main__` o liga, pela ToolLayer."""

    def setUp(self) -> None:
        remendo = mock.patch.object(rep, "por_referencia", lambda _l, _t, referencia: QID if referencia == REFERENCIA else None)
        remendo.start()
        self.addCleanup(remendo.stop)

    def _camada(self, cliente: ClienteDoCom | None, ligacoes: int | None = None) -> ToolLayer:
        especificacao = catalogo_do_piloto(
            orcamento_tools.executores(lambda: AGORA, cliente_do_com=cliente)
        )["submit_quote"]
        return ToolLayer(
            Catalogo((especificacao,)), abrir_ligacao=_Ligacao(outro=LOJA).nova_vaga, ligacoes=ligacoes
        )

    @staticmethod
    async def _invocar(camada: ToolLayer, condicoes: str | None = LIMPAS):
        argumentos = {"referencia": REFERENCIA, "valor": "120 mil"}
        if condicoes is not None:
            argumentos["condicoes"] = condicoes
        return await camada.invoke(contexto(vertical="dono"), "submit_quote", argumentos, allowed=("submit_quote",))

    def _sem_base(self) -> None:
        remendo = mock.patch.object(rep, "gravar_a_resposta_do_dono", _gravar_sem_base)
        remendo.start()
        self.addCleanup(remendo.stop)

    def _assert_recusa(self, resultado: Any) -> None:
        self.assertFalse(resultado.ok)
        self.assertEqual((resultado.error.codigo, resultado.error.detalhe), (VALIDATION_ERROR, regras.CONDICOES_RECUSADAS))


class TestASegue(_Montagem):
    """Criterio 1: a porta chega ao `responder`, e o `screen` corre numa *thread*."""

    def test_condicoes_limpas_seguem_pelo_com_e_pelo_classificador(self) -> None:
        self._sem_base()

        async def turno():
            async with _AgrNoCiclo() as agr:
                with _ComDeEnsaio(agr.url) as com:
                    resultado = await self._invocar(self._camada(_cliente(com.base)))
                return resultado, agr.chamadas, com.pedidos

        resultado, chamadas_ao_agr, pedidos = asyncio.run(turno())
        self.assertTrue(resultado.ok, resultado.error)
        self.assertIn(LIMPAS, resultado.data["previsao"])
        self.assertEqual(chamadas_ao_agr, 1)
        # Uma chamada ao COM, com o sujeito das condicoes, o `quote_id` como
        # referencia, a categoria do tenant e os dois cabecalhos.
        self.assertEqual(len(pedidos), 1)
        cabecalhos, corpo = pedidos[0]
        self.assertEqual(cabecalhos[CABECALHO_INTERNO], CREDENCIAL)
        self.assertEqual(cabecalhos[CABECALHO_TENANT], TENANT)
        self.assertEqual(
            {k: corpo[k] for k in ("sujeito_tipo", "sujeito_ref", "categoria_declarada", "textos")},
            {"sujeito_tipo": "condicoes", "sujeito_ref": QID, "categoria_declarada": None, "textos": [LIMPAS]},
        )
        self.assertEqual(corpo["actor"], {"kind": "agente", "id": "grafo-dono"})
        # KAM-230: a finalidade propria, e o prazo que sobra ao `screen`.
        self.assertEqual(corpo["finalidade"], FINALIDADE_CONDICOES)
        self.assertIsInstance(corpo["prazo_ms"], int)
        self.assertLessEqual(corpo["prazo_ms"], 8_000 - orcamento_tools.RESERVA_DA_TRANSACCAO_MS)

    def test_com_o_ciclo_preso_as_condicoes_recusam(self) -> None:
        """O canario: o mesmo executor **no ciclo** deixa o COM sem AGR, e recusa."""
        self._sem_base()
        modelo = orcamento_tools.ArgumentosDeSubmitQuote(referencia=REFERENCIA, valor="120 mil", condicoes=LIMPAS)

        async def turno():
            async with _AgrNoCiclo() as agr:
                with _ComDeEnsaio(agr.url) as com:
                    no_ciclo = orcamento_tools.executores(lambda: AGORA, cliente_do_com=_cliente(com.base))["submit_quote"]
                    pedido = Pedido(ctx=contexto(vertical="dono"), args=modelo, timeout_ms=8_000, ligacao=_Ligacao())
                    with self.assertRaises(ErroDeBackend) as caso:
                        no_ciclo(pedido)  # sem `to_thread`: o ciclo fica preso
                    # O ciclo volta: a ligacao que o COM abriu durante o `screen`
                    # e aceite agora, ja abandonada.
                    await asyncio.sleep(0.3)
                return caso.exception, agr.ligacoes, agr.chamadas

        erro, ligacoes, chamadas_ao_agr = asyncio.run(turno())
        self.assertEqual((erro.codigo, erro.detalhe), (VALIDATION_ERROR, regras.CONDICOES_RECUSADAS))
        # O COM chamou o AGR, e o AGR so o viu depois de o executor recusar. Um
        # COM que nao chamasse ninguem dava zero aqui. (As `chamadas` podem ser
        # 0 ou 1: o pedido tardio ainda se le inteiro do *buffer*.)
        self.assertEqual(ligacoes, 1)
        del chamadas_ao_agr

    def test_sem_condicoes_nao_vai_ao_com(self) -> None:
        self._sem_base()
        with _ComDeEnsaio() as com:
            resultado = asyncio.run(self._invocar(self._camada(_cliente(com.base)), condicoes=None))
        self.assertTrue(resultado.ok, resultado.error)
        self.assertEqual(com.pedidos, [])

    def test_sem_com_as_condicoes_recusam_e_sem_elas_segue(self) -> None:
        """Sem `KAMBA_COM_URL` nao ha porta: a `ScreeningPorLigar` recusa."""
        self._sem_base()
        camada = self._camada(None)
        self._assert_recusa(asyncio.run(self._invocar(camada)))
        self.assertTrue(asyncio.run(self._invocar(self._camada(None), condicoes=None)).ok)


class TestRecusa(_Montagem):
    """Os casos adversariais: o `responder` real, que recusa antes da base."""

    def test_cerveja_recusa_pela_guarda_antes_do_com(self) -> None:
        """«Cerveja» recusa com `condicoes_recusadas`, e pela guarda do KAM-033: o COM nao a ve.

        A recusa que vem do `screen` e o caso «brinde» do ensaio seguinte.
        """
        with _ComDeEnsaio() as com:
            resultado = asyncio.run(self._invocar(self._camada(_cliente(com.base)), "entrega com cerveja gelada"))
        self._assert_recusa(resultado)
        self.assertEqual(com.pedidos, [])

    def test_uma_regra_da_politica_recusa_sem_o_texto_em_registo_nenhum(self) -> None:
        saida, erros = io.StringIO(), io.StringIO()
        apanhado = io.StringIO()
        manipulador = logging.StreamHandler(apanhado)
        raiz = logging.getLogger()
        nivel = raiz.level
        raiz.addHandler(manipulador)
        raiz.setLevel(logging.DEBUG)
        try:
            with _ComDeEnsaio() as com, contextlib.redirect_stdout(saida), contextlib.redirect_stderr(erros):
                resultado = asyncio.run(self._invocar(self._camada(_cliente(com.base)), BLOQUEADAS))
        finally:
            raiz.removeHandler(manipulador)
            raiz.setLevel(nivel)
        self._assert_recusa(resultado)
        # A recusa veio do `screen`, e nao da guarda.
        self.assertEqual(len(com.pedidos), 1)
        for registo in (saida.getvalue(), erros.getvalue(), apanhado.getvalue(), repr(resultado)):
            self.assertNotIn("brinde", registo)

    def test_com_em_baixo_recusa_depressa(self) -> None:
        casos = {
            "503": lambda: _ComDeEnsaio(modo="em_baixo"),
            "porta fechada": None,
        }
        for nome, fabrica in casos.items():
            with self.subTest(caso=nome):
                inicio = time.monotonic()
                if fabrica is None:
                    resultado = asyncio.run(self._invocar(self._camada(_cliente(f"http://127.0.0.1:{_porta_livre()}"))))
                else:
                    with fabrica() as com:
                        resultado = asyncio.run(self._invocar(self._camada(_cliente(com.base))))
                self._assert_recusa(resultado)
                # Abaixo do tecto de uma `write` (8 s): o turno nao fica preso.
                # Folgado de proposito: no Windows, uma ligacao recusada leva ~2 s.
                self.assertLess(time.monotonic() - inicio, 6.0)

    def test_agr_em_baixo_durante_o_screen_recusa(self) -> None:
        """O COM responde, mas o classificador nao: `condicional`, e recusa."""
        with _ComDeEnsaio(f"http://127.0.0.1:{_porta_livre()}/internal/screening") as com:
            resultado = asyncio.run(self._invocar(self._camada(_cliente(com.base))))
        self._assert_recusa(resultado)
        self.assertEqual(len(com.pedidos), 1)

    def test_um_com_lento_nao_prende_o_turno(self) -> None:
        """O `screen` corta no tecto do executor menos a reserva, e nao nos 20 s.

        Com o tecto de escrita a 2,5 s, o `screen` tem ~1 s; o COM dorme 4 s. A
        recusa e `condicoes_recusadas`, e nao o `UPSTREAM_TIMEOUT` que a ToolLayer
        da aos 3 s (2,5 s mais a margem) com a *thread* ainda a correr: e o codigo
        que o prova, e o tempo e so a cota.
        """
        with mock.patch.dict(os.environ, {VARIAVEL_DE_TIMEOUT_ESCRITA: "2500"}):
            with _ComDeEnsaio(modo="lento", atraso_s=4.0) as com:
                camada = self._camada(_cliente(com.base))
                inicio = time.monotonic()
                resultado = asyncio.run(self._invocar(camada))
                decorrido = time.monotonic() - inicio
        self._assert_recusa(resultado)
        self.assertLess(decorrido, 3.5)


class TestAFinalidade(_Montagem):
    """A decisao do fundador de 2026-11-20 (opcao B): as condicoes tem finalidade propria.

    Substitui o `test_sem_finalidade_as_condicoes_recusam_sem_ir_ao_com` do
    KAM-228, que media a porta fechada: aqui a finalidade sai do AGR no corpo do
    COM e chega ao classificador. O *gate* que a consulta — e que recusa as
    condicoes a um tenant so com o destino do catalogo — e o
    `test_llm_screening.py`; os dois processos com a base, o `db/tests_entrada/test_screen_com.py`.
    """

    def test_a_finalidade_e_propria_e_esta_no_dominio(self) -> None:
        self.assertEqual(orcamento_tools.FINALIDADE_DAS_CONDICOES, "classificacao_de_condicoes")
        self.assertEqual(orcamento_tools.FINALIDADE_DAS_CONDICOES, FINALIDADE_CONDICOES)
        self.assertNotEqual(orcamento_tools.FINALIDADE_DAS_CONDICOES, FINALIDADE_CLASSIFICACAO)
        self.assertIn(FINALIDADE_CONDICOES, FINALIDADES)
        # O produto continua com a do catalogo.
        self.assertEqual(ponte.FINALIDADE_DO_SUJEITO[ponte.SUJEITO_DO_PRODUTO], FINALIDADE_CLASSIFICACAO)

    def test_a_finalidade_das_condicoes_chega_ao_classificador(self) -> None:
        self._sem_base()

        async def turno():
            async with _AgrNoCiclo() as agr:
                with _ComDeEnsaio(agr.url) as com:
                    resultado = await self._invocar(self._camada(_cliente(com.base)))
                return resultado, agr.corpos

        resultado, corpos = asyncio.run(turno())
        self.assertTrue(resultado.ok, resultado.error)
        self.assertEqual([c["finalidade"] for c in corpos], [FINALIDADE_CONDICOES])

    def test_a_tabela_do_sujeito_e_a_do_com(self) -> None:
        """A tabela do adaptador e a do `operacaoDeScreen`, lida do TypeScript.

        O COM confere a finalidade que o AGR manda contra a dele: duas tabelas
        que divergissem recusavam todas as condicoes (ou todos os produtos).
        """
        texto = (RAIZ / "services/com/src/screening/index.ts").read_text(encoding="utf-8")
        bloco = texto.split("export const FINALIDADE_DO_SUJEITO", 1)[1].split("};", 1)[0]
        self.assertIn("[SUJEITO_DAS_CONDICOES]: FINALIDADE_DAS_CONDICOES", bloco)
        self.assertIn("[SUJEITO_DO_PRODUTO]: FINALIDADE_DO_CATALOGO", bloco)
        # KAM-121: o conteudo do social, com a finalidade propria.
        self.assertIn("[SUJEITO_DO_CONTEUDO]: FINALIDADE_DO_CONTEUDO", bloco)
        classificador = (RAIZ / "packages/core-ts/src/screening/classificador.ts").read_text(encoding="utf-8")
        self.assertIn(f'FINALIDADE_DAS_CONDICOES = "{FINALIDADE_CONDICOES}"', classificador)
        self.assertIn(f'FINALIDADE_DO_CATALOGO = "{FINALIDADE_CLASSIFICACAO}"', classificador)
        self.assertIn('FINALIDADE_DO_CONTEUDO = "classificacao_de_conteudo"', classificador)
        self.assertEqual(ponte.FINALIDADE_DO_SUJEITO[ponte.SUJEITO_DO_CONTEUDO], "classificacao_de_conteudo")
        self.assertEqual(set(ponte.FINALIDADE_DO_SUJEITO), set(ponte.SUJEITOS))


class TestOPrazo(_Montagem):
    """O `Pedido.prazo` conta do inicio da ToolLayer, e nao do executor (achado 3 do KAM-228)."""

    def test_o_prazo_e_o_inicio_da_espera_mais_o_tecto(self) -> None:
        vistos: list[tuple[float | None, int]] = []
        especificacao = catalogo_do_piloto(
            orcamento_tools.executores(lambda: AGORA, cliente_do_com=None)
        )["submit_quote"]
        executor = especificacao.executor

        def espiao(pedido: Pedido):  # noqa: ANN202
            vistos.append((pedido.prazo, pedido.timeout_ms))
            return executor(pedido)

        self._sem_base()
        camada = ToolLayer(
            Catalogo((dataclasses.replace(especificacao, executor=espiao),)),
            abrir_ligacao=_Ligacao(outro=LOJA).nova_vaga,
        )
        antes = time.monotonic()
        resultado = asyncio.run(self._invocar(camada, condicoes=None))
        self.assertTrue(resultado.ok, resultado.error)
        ((prazo, timeout_ms),) = vistos
        assert prazo is not None
        # Entre o inicio do `invoke` e o do executor: o prazo ja corria.
        self.assertGreaterEqual(prazo, antes + timeout_ms / 1000)
        self.assertLess(prazo, antes + timeout_ms / 1000 + 1.0)

    def test_o_restante_conta_do_prazo_e_nao_do_executor(self) -> None:
        modelo = orcamento_tools.ArgumentosDeSubmitQuote(referencia=REFERENCIA, valor="120 mil")
        agora = time.monotonic()
        pedido = Pedido(ctx=contexto(vertical="dono"), args=modelo, timeout_ms=8_000, prazo=agora + 3.0)
        # O executor acabou de comecar, mas a ToolLayer ja gastou 5 s.
        self.assertLess(orcamento_tools.restante_ms(pedido, agora), 3_000)
        self.assertGreater(orcamento_tools.restante_ms(pedido, agora), 2_500)
        sem_prazo = Pedido(ctx=contexto(vertical="dono"), args=modelo, timeout_ms=8_000)
        self.assertGreater(orcamento_tools.restante_ms(sem_prazo, agora), 7_500)

    def test_passado_o_prazo_depois_do_screen_nao_grava(self) -> None:
        """O `screen` acaba depois do prazo: nada se grava, e o dono ja teve o `UPSTREAM_TIMEOUT`."""
        gravadas: list[Any] = []
        self._sem_base()
        remendo = mock.patch.object(rep, "gravar_a_resposta_do_dono", lambda *a: gravadas.append(a))
        remendo.start()
        self.addCleanup(remendo.stop)
        modelo = orcamento_tools.ArgumentosDeSubmitQuote(referencia=REFERENCIA, valor="120 mil", condicoes=LIMPAS)
        executor = orcamento_tools.executores(lambda: AGORA, cliente_do_com=None)["submit_quote"]
        pedido = Pedido(
            ctx=contexto(vertical="dono"), args=modelo, timeout_ms=8_000, ligacao=_Ligacao(),
            prazo=time.monotonic() + 0.2,
            largar_tomada=lambda trabalho: (time.sleep(0.3), (LIMPAS, _Ligacao()))[1],
        )
        with self.assertRaises(ErroDeBackend) as caso:
            executor(pedido)
        self.assertEqual(caso.exception.codigo, "UPSTREAM_TIMEOUT")
        self.assertEqual(gravadas, [])


class TestATomada(_Montagem):
    """O `screen` corre sem a tomada da ToolLayer (achado 9 do KAM-228)."""

    def test_com_uma_tomada_outra_invocacao_corre_durante_o_screen(self) -> None:
        """Uma tomada so; o COM demora 1,5 s; a segunda invocacao acaba antes da primeira.

        O canario e o mesmo executor sem largar a tomada: a segunda espera pela
        primeira (`test_sem_largar_a_tomada_a_segunda_espera`).
        """
        self._sem_base()
        ordem = asyncio.run(self._duas(largar=True))
        self.assertEqual(ordem, ["sem_condicoes", "com_condicoes"])

    def test_sem_largar_a_tomada_a_segunda_espera(self) -> None:
        self._sem_base()
        remendo = mock.patch.object(Pedido, "sem_tomada", lambda self, trabalho: (trabalho(), self.ligacao))
        remendo.start()
        self.addCleanup(remendo.stop)
        ordem = asyncio.run(self._duas(largar=False))
        self.assertEqual(ordem, ["com_condicoes", "sem_condicoes"])

    async def _duas(self, *, largar: bool) -> list[str]:
        del largar
        ordem: list[str] = []
        with _ComDeEnsaio(modo="lento", atraso_s=1.5) as com:
            camada = self._camada(_cliente(com.base), ligacoes=1)

            async def uma(nome: str, condicoes: str | None) -> None:
                await self._invocar(camada, condicoes=condicoes)
                ordem.append(nome)

            primeira = asyncio.create_task(uma("com_condicoes", LIMPAS))
            # A primeira ja tem a tomada e esta no `screen`.
            while not com.pedidos:
                await asyncio.sleep(0.01)
            await asyncio.gather(primeira, uma("sem_condicoes", None))
        return ordem


# ------------------------------------------------------------------ a porta


class TestAPortaDasCondicoes(unittest.TestCase):
    def _pedido(self, timeout_ms: int = 8_000) -> Pedido:
        modelo = orcamento_tools.ArgumentosDeSubmitQuote(referencia=REFERENCIA, valor="120 mil")
        return Pedido(ctx=contexto(vertical="dono"), args=modelo, timeout_ms=timeout_ms)

    def test_sem_cliente_nao_ha_porta(self) -> None:
        self.assertIsNone(orcamento_tools.porta_das_condicoes(None, self._pedido(), 8_000))

    def test_a_porta_e_a_do_sujeito_das_condicoes_com_a_vertical_do_turno(self) -> None:
        porta = orcamento_tools.porta_das_condicoes(_cliente("http://com:3002"), self._pedido(), 8_000)
        assert isinstance(porta, ponte.ScreeningPeloCom)
        self.assertEqual((porta.sujeito_tipo, porta.vertical), ("condicoes", "dono"))
        self.assertIn(orcamento_tools.SUJEITO_DAS_CONDICOES, ponte.SUJEITOS)

    def test_o_tecto_e_o_que_sobra_menos_a_reserva(self) -> None:
        cliente = _cliente("http://com:3002")
        reserva = orcamento_tools.RESERVA_DA_TRANSACCAO_MS
        porta = orcamento_tools.porta_das_condicoes(cliente, self._pedido(), 7_800)
        self.assertEqual(porta.timeout_ms, 7_800 - reserva)
        # Nunca acima dos 20 s do adaptador.
        self.assertEqual(orcamento_tools.porta_das_condicoes(cliente, self._pedido(), 60_000).timeout_ms,
                         ponte.TEMPO_MAXIMO_MS)
        # Sem tempo que sobre, nao ha porta, e as condicoes recusam.
        self.assertIsNone(orcamento_tools.porta_das_condicoes(cliente, self._pedido(), reserva))


class TestOArranque(unittest.TestCase):
    """O `__main__` liga a porta pelo mesmo cliente das tools de comercio."""

    def test_o_cliente_do_com_le_o_endereco(self) -> None:
        log = mock.Mock()
        credencial = arranque.CredencialDoCom()
        with mock.patch.dict(os.environ, {arranque.VARIAVEL_DO_COM: " http://com:3002 "}):
            cliente = arranque._cliente_do_com(log, credencial)
        assert cliente is not None
        self.assertEqual(cliente.base, "http://com:3002")
        with mock.patch.dict(os.environ, {arranque.VARIAVEL_DO_COM: ""}):
            self.assertIsNone(arranque._cliente_do_com(log, credencial))
        log.warn.assert_called_once_with(outcome="com_sem_endereco")

    def test_o_main_passa_o_cliente_as_tools_do_orcamento(self) -> None:
        """A ligacao, e nao so a funcao: um `executores()` sem o cliente passava tudo o resto."""
        texto = (RAIZ / "services/agr/src/kamba_agr/__main__.py").read_text(encoding="utf-8")
        self.assertIn("orcamento_tools.executores(cliente_do_com=cliente_do_com)", texto)
        self.assertIn("_executores_do_comercio(cliente_do_com)", texto)
        # E o cliente liga as tools de comercio; sem ele, nenhuma.
        self.assertEqual(arranque._executores_do_comercio(None), {})
        self.assertTrue(arranque._executores_do_comercio(_cliente("http://com:3002")))


if __name__ == "__main__":
    unittest.main()
