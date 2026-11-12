"""A sonda do AGR responde 200 com servico, versao e commit.

Conduz a aplicacao ASGI directamente, em vez de usar o `TestClient` do Starlette:
o `TestClient` exige `httpx`, e acrescentar `httpx` ao lock do AGR para testar uma
rota que devolve quatro campos seria pagar uma arvore de dependencias em producao
por conveniencia de teste. O protocolo ASGI e estavel e a chamada directa exercita
o encaminhamento real do Starlette.
"""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

from kamba_agr.app import create_app
from kamba_agr.meta import SERVICE, VERSION

ROOT = Path(__file__).resolve().parents[3]
SCHEMA = ROOT / "packages" / "contracts" / "schemas" / "healthz.response.v1.json"


async def _request(app, path: str, method: str = "GET") -> tuple[int, dict, bytes]:
    """Faz um pedido HTTP a uma aplicacao ASGI sem servidor nem cliente HTTP."""
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [(b"host", b"testserver")],
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
    }

    received: list[dict] = []

    async def receive() -> dict:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict) -> None:
        received.append(message)

    await app(scope, receive, send)

    start = next(m for m in received if m["type"] == "http.response.start")
    body = b"".join(
        m.get("body", b"") for m in received if m["type"] == "http.response.body"
    )
    headers = {k.decode().lower(): v.decode() for k, v in start.get("headers", [])}
    return start["status"], headers, body


def request(path: str, method: str = "GET") -> tuple[int, dict, bytes]:
    return asyncio.run(_request(create_app(), path, method))


class TestHealthz(unittest.TestCase):
    def test_responde_200_com_os_campos_do_contrato(self) -> None:
        status, headers, body = request("/healthz")

        self.assertEqual(status, 200)
        self.assertIn("application/json", headers.get("content-type", ""))

        payload = json.loads(body)
        self.assertEqual(sorted(payload), ["commit", "service", "status", "version"])
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["service"], SERVICE)
        self.assertEqual(payload["version"], VERSION)

    def test_conforme_aos_padroes_do_esquema(self) -> None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        payload = json.loads(request("/healthz")[2])

        self.assertIn(payload["service"], schema["properties"]["service"]["enum"])
        self.assertRegex(
            payload["version"], re.compile(schema["properties"]["version"]["pattern"])
        )
        self.assertRegex(
            payload["commit"], re.compile(schema["properties"]["commit"]["pattern"])
        )

    def test_rota_desconhecida_nao_responde_200(self) -> None:
        # A `/metrics` saiu desta lista com o **KAM-080**, que lhe criou a rota.
        # Nao e o teste a ceder ao codigo: quando esta linha foi escrita o AGR
        # nao tinha `/metrics` e o 404 era o comportamento correcto a prender.
        # O que mudou foi o comportamento, de proposito e com ticket — e a
        # prova de que mudou e o `TestMetricas` abaixo.
        #
        # **E nao se substituiu por `/metrics/`.** A primeira correccao fez
        # isso, e o `/metrics/` nao e uma rota desconhecida: o Starlette tem
        # `redirect_slashes` e devolve **307** para `/metrics`, pelo que o
        # `assertNotEqual(307, 200)` passava trivialmente e o teste deixava de
        # afirmar o que o nome promete. Medido. O que esta aqui sao caminhos que
        # **nao** redireccionam para nada.
        for path in ("/", "/metricas", "/metrics/extra", "/admin"):
            with self.subTest(path=path):
                self.assertEqual(request(path)[0], 404)

    def test_as_duas_rotas_com_barra_final_redireccionam_e_nao_sao_404(self) -> None:
        """O que o teste acima **nao** afirma, dito em separado.

        O `redirect_slashes` do Starlette esta ligado, logo `/healthz/` e
        `/metrics/` dao **307** e nao 404. Isto prende-o para que ninguem volte
        a usar uma barra final como se fosse um caminho desconhecido.
        """
        for path in ("/healthz/", "/metrics/"):
            with self.subTest(path=path):
                self.assertEqual(request(path)[0], 307)

    def test_healthz_so_aceita_get(self) -> None:
        for method in ("POST", "DELETE", "PUT"):
            with self.subTest(method=method):
                self.assertEqual(request("/healthz", method)[0], 405)


class TestMetricas(unittest.TestCase):
    """A rota `/metrics` do KAM-080 — as 44 metricas que o AGR nao servia."""

    def test_metrics_responde_200_em_texto(self) -> None:
        estado, cabecalhos, _corpo = request("/metrics")
        self.assertEqual(estado, 200)
        tipo = cabecalhos.get("content-type", "")
        # O formato de exposicao e `text/plain; version=0.0.4`. Um
        # `application/json` fazia o *scraper* recusar a resposta, e e por isso
        # que o tipo se prende e nao so o codigo.
        self.assertIn("text/plain", tipo)
        self.assertIn("version=0.0.4", tipo)

    def test_metrics_so_aceita_get(self) -> None:
        for method in ("POST", "DELETE", "PUT"):
            with self.subTest(method=method):
                self.assertEqual(request("/metrics", method)[0], 405)

    def test_um_processo_fresco_serve_corpo_vazio(self) -> None:
        """**Uma divergencia medida, e nao um defeito desta rota.**

        O `exposicao()` do AGR faz `if not series: continue`: uma metrica que
        ainda nao foi contada **nao aparece**, nem com `# HELP`. Logo um processo
        acabado de arrancar serve um corpo vazio.

        Isto contraria a regra que os modulos TypeScript escrevem — «as series
        aparecem sempre, mesmo a zero», porque «um painel que mostre *sem dados*
        nao distingue *ninguem foi recusado* de *o processo nao arrancou*»
        (`services/com/src/metricas.ts`, `packages/core-ts/src/ten/metricas.ts`).

        **Nao se corrigiu aqui, e a razao nao e falta de tempo:** o
        comportamento esta preso por tres testes de outro ticket —
        `test_metricas.py::test_a_exposicao_vazia_e_vazia` exige exactamente
        `""`, e `test_degradacao.py` exige duas vezes que uma metrica **nao**
        apareca antes de acontecer. E uma decisao do modulo (KAM-025/KAM-037),
        nao um descuido, e inverte-la e mexer no criterio de outro ticket.

        O que **nao** se perde: o `up` do Prometheus fica a 1 (o alvo responde
        200), pelo que «o processo nao arrancou» continua distinguivel — pelo
        `up` e nao pela serie. Fica registado em `docs/observabilidade.md` §5.

        ## Porque e que isto corre num subprocesso

        **Porque a premissa e «processo fresco», e um ensaio dentro de uma suite
        nao esta num.** O registo de metricas e global ao processo, e o alvo
        `ordem-dos-ensaios` (KAM-173) corre a suite nas duas ordens: na inversa,
        outro ensaio desta pasta ja contou um evento antes deste, e o corpo
        deixa de estar vazio. O gate 4 mediu-o:

            AssertionError: b'# HELP agr_evt_consumidos_total ...' != b''

        **Nao foi um falso alarme: foi o portao a fazer o que existe para
        fazer.** A primeira versao assumia a premissa em vez de a controlar, e
        um ensaio que assume a sua premissa passa pela ordem em que calhou.

        E **nao se trocou por limpar o registo no `setUp`**: isso fecharia o
        portao e passaria a medir «registo limpo» em vez de «processo fresco»,
        com o nome do ensaio a prometer mais do que ele ve. O subprocesso mede o
        que a frase diz.

        O que este ensaio acrescenta ao do outro ticket, e a razao de nao ser
        uma copia: aquele prende o `exposicao()`, esta prende a **rota** — que o
        `PlainTextResponse` nao acrescenta cabecalho, prefixo nem linha a uma
        exposicao vazia.
        """
        sonda = Path(__file__).resolve().parent / "sonda_de_processo_fresco.py"
        corrida = subprocess.run(
            [sys.executable, str(sonda)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(
            corrida.returncode, 0, f"a sonda falhou: {corrida.stderr[-600:]}"
        )
        self.assertEqual(
            corrida.stdout.strip(),
            "200 0",
            f"esperava «200 0» (200 e zero octetos); stderr: {corrida.stderr[-300:]}",
        )

    def test_depois_de_contar_o_corpo_traz_o_formato_sem_identificadores(self) -> None:
        """O formato de exposicao, e o `OBS-I` medido **na saida**.

        E a unica verificacao desta arvore que le o **texto servido** em vez do
        codigo que o produz: o `obs_lint` verifica o catalogo e as regras, e nao
        ve o que um processo emite de facto.
        """
        from kamba_agr import metricas as modulo

        self.addCleanup(modulo.METRICAS.repor)
        for desfecho in modulo.DESFECHOS:
            modulo.METRICAS.contar(modulo.METRICA_TURNOS, desfecho)
        modulo.METRICAS.medir(modulo.METRICA_FILA, 3)

        corpo = request("/metrics")[2].decode("utf-8")
        self.assertIn(f"# HELP {modulo.METRICA_TURNOS}", corpo)
        self.assertIn(f"# TYPE {modulo.METRICA_TURNOS} counter", corpo)
        self.assertIn(f"{modulo.METRICA_FILA} 3", corpo)

        proibidas = (
            "contact_id",
            "contact_hmac",
            "telefone",
            "phone",
            "msisdn",
            "bsuid",
            "wamid",
            "tenant_id",
        )
        series = [
            linha
            for linha in corpo.splitlines()
            if not linha.startswith("#") and "{" in linha
        ]
        self.assertTrue(series, "sem series nao se mede nada")

        # Duas metades, e a segunda e a que importa.
        #
        # A primeira — os **nomes** de etiqueta — era a unica que este teste
        # fazia, e a revisao adversarial mostrou que **nao pode falhar**: os
        # nomes de eixo do AGR vem de dois literais (`_COM_MOTIVO` e
        # `_NOME_DO_EIXO`, com `outcome` por omissao), pelo que um `contact_id=`
        # e impossivel por construcao. Fica, porque e barata e porque um
        # literal novo pode sempre ser escrito errado — mas sozinha era prova
        # tautologica.
        #
        # A segunda — os **valores** — e onde um identificador podia de facto
        # viajar: o valor vem de quem chama o `contar`, e e por isso que a
        # gramatica existe. E o que esta metade mede.
        formas_de_identificador = (
            re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"),
            re.compile(r"(?:\+|00)?244\d{9}"),
            re.compile(r"\b9\d{8}\b"),
            re.compile(r"[0-9a-f]{32}"),
            re.compile(r"\bwamid\.[A-Za-z0-9_=-]+"),
        )
        for linha in series:
            etiquetas = linha[linha.index("{") + 1 : linha.rindex("}")]
            for proibida in proibidas:
                self.assertNotIn(
                    f"{proibida}=",
                    etiquetas,
                    f"{proibida} em {linha[: linha.index('{')]}",
                )
            for forma in formas_de_identificador:
                self.assertIsNone(
                    forma.search(etiquetas),
                    f"forma de identificador {forma.pattern} em {linha[: linha.index('{')]}",
                )

    def test_a_rota_serve_tambem_as_metricas_do_idx(self) -> None:
        """KAM-193: o registo do `kamba_core.idx` sai na mesma `/metrics`.

        Sem a linha da rota, o registo enchia-se no executor e nao saia em
        sitio nenhum — medido e invisivel, que e o defeito que o `exposicao()`
        do AGR ja pagou com as medidas etiquetadas.
        """
        from kamba_core.idx import metricas as idx

        self.addCleanup(idx.METRICAS.repor)
        idx.METRICAS.registar_pesquisa(modo="lexical", duracao_ms=41, resultados=3)

        corpo = request("/metrics")[2].decode("utf-8")
        self.assertIn('idx_query_ms{ramo="todos",modo="lexical"} 41', corpo)
        self.assertIn("idx_results_total 3", corpo)
        self.assertIn('idx_mode{modo="lexical"} 1', corpo)
        self.assertIn("# TYPE idx_mode counter", corpo)


class TestMetadados(unittest.TestCase):
    def test_o_servico_e_o_da_topologia(self) -> None:
        self.assertEqual(SERVICE, "agr")

    def test_a_versao_e_semver(self) -> None:
        self.assertRegex(VERSION, r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?$")

    def test_a_rota_healthz_esta_registada(self) -> None:
        rotas = {getattr(r, "path", None) for r in create_app().routes}
        self.assertIn("/healthz", rotas)


if __name__ == "__main__":
    unittest.main()
