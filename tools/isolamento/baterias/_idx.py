"""O ataque as tres rotas do processo do IDX (KAM-194), num servidor em processo.

Separado do `x01_rotas.py` pela razao do `_agr.py`: o `x01_rotas` tem de ser
importavel a seco, e este modulo importa o `kamba_core.idx`. Importa-se dentro
do `fn`.

## Um servidor de verdade, numa porta efemera

A rota e um `BaseHTTPRequestHandler` da biblioteca padrao, e nao uma aplicacao
ASGI: nao ha chamavel para conduzir em processo. O caso levanta o
`ThreadingHTTPServer` do proprio `processo.servidor` em `127.0.0.1:0`, com a
**mesma** classe de pedido que o processo serve, e fala com ele por
`http.client`. Nenhuma camada entre o caso e a rota, e nada fica a escutar fora
do *loopback*.

## O que «A usa IDs de B» quer dizer nesta superficie

O mesmo que na `/internal/event` do AGR: a credencial e **da instancia**
(`idx_internal_token`), quem chama e a nossa ponte, e o *tenant* vem do
envelope. O que se ataca e a porta: sem a credencial, ou com uma credencial que
e o proprio canario de B, a rota recusa **antes** de ler o corpo, de forma
uniforme, e a porta da entrega nunca e chamada. O que a entrega faz com um
envelope cujos ponteiros divergem e da suite do `kamba_core.idx.entrega` (DLQ
sem envelope); aqui afirma-se que a rota nao o deixa chegar la sem credencial e
que nada de B sai na resposta nem no registo.
"""

from __future__ import annotations

import http.client
import json
import sys
import threading
import uuid
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[3]

#: A credencial do ensaio. Nao e um segredo: o servidor compara-a com o que a
#: funcao `credencial` devolve, e as duas vivem neste ficheiro.
CREDENCIAL = "credencial-interna-do-x01-idx"

ITEM_DO_EVENTO = "rota:py-core:kamba_core/idx/processo:tratador:POST:/internal/event"
ITEM_DA_SONDA = "rota:py-core:kamba_core/idx/processo:tratador:GET:/healthz"
ITEM_DAS_METRICAS = "rota:py-core:kamba_core/idx/processo:tratador:GET:/metrics"


def _no_caminho() -> None:
    caminho = str(RAIZ / "libs/py-core/src")
    if caminho not in sys.path:
        sys.path.insert(0, caminho)


class _EntregaRegistadora:
    """O duplo da porta da entrega: registra o corpo e responde `aplicado`."""

    def __init__(self) -> None:
        self.corpos: list[Any] = []

    def entregar(self, corpo: Any) -> Any:
        from kamba_core.idx.entrega import Resposta  # noqa: PLC0415

        self.corpos.append(corpo)
        return Resposta(200, "aplicado")


class _Servidor:
    """O `processo.servidor` numa porta efemera, a correr numa *thread*."""

    def __init__(self, entrega: _EntregaRegistadora, registo: list[str]) -> None:
        _no_caminho()
        from kamba_core.idx import processo  # noqa: PLC0415

        def ao_responder(outcome: str, estado: int) -> None:
            # A mesma linha que o `__main__` escreve, para o oraculo ter o que
            # varrer na origem `logs`.
            registo.append(json.dumps({"outcome": outcome, "error_code": f"http_{estado}"}))

        self.http = processo.servidor(
            0, entrega, lambda: CREDENCIAL, anfitriao="127.0.0.1", ao_responder=ao_responder
        )
        self.porta = self.http.server_address[1]
        self._thread = threading.Thread(target=self.http.serve_forever, daemon=True)

    def __enter__(self) -> _Servidor:
        self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.http.shutdown()
        self.http.server_close()

    def pedir(
        self,
        metodo: str,
        caminho: str,
        corpo: bytes = b"",
        cabecalhos: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, str], str]:
        ligacao = http.client.HTTPConnection("127.0.0.1", self.porta, timeout=10)
        try:
            ligacao.request(metodo, caminho, body=corpo or None, headers=cabecalhos or {})
            resposta = ligacao.getresponse()
            texto = resposta.read().decode("utf-8", errors="replace")
            return resposta.status, dict(resposta.getheaders()), texto
        finally:
            ligacao.close()


def _envelope(tenant_id: str, event_id: str) -> dict:
    return {
        "event_id": event_id,
        "tenant_id": tenant_id,
        "tentativas": 1,
        "envelope": {"event_id": event_id, "tenant_id": tenant_id, "tipo": "offer.updated"},
    }


def atacar_rota_interna(ctx: Any) -> list[str]:
    """O X-01 da `POST /internal/event` do IDX."""
    from .x01_rotas import _uniformidade  # noqa: PLC0415

    canario_de_b = next(iter(ctx.oraculo.proibidos.values()))
    b = ctx.b.id
    entrega = _EntregaRegistadora()
    registo: list[str] = []
    achados: list[str] = []
    json_ = {"content-type": "application/json"}

    ataques = [
        # Sem credencial, com o tenant e o canario de B no corpo.
        (_envelope(b, canario_de_b), dict(json_)),
        # Com o canario de B **como** credencial: um valor que existe, e e de B.
        (_envelope(b, str(uuid.uuid4())), {**json_, "x-kamba-interno": canario_de_b}),
        # Com uma credencial errada e o canario de B no corpo.
        (_envelope(b, canario_de_b), {**json_, "x-kamba-interno": "outra-credencial"}),
    ]
    estados: list[int] = []
    corpos: set[str] = set()
    with _Servidor(entrega, registo) as servidor:
        for corpo, cabecalhos in ataques:
            estado, cab, texto = servidor.pedir(
                "POST", "/internal/event", json.dumps(corpo).encode(), cabecalhos
            )
            estados.append(estado)
            corpos.add(texto)
            achados.extend(
                f"{ITEM_DO_EVENTO}: {fuga}"
                for fuga in ctx.oraculo.varrer_tudo(
                    {"corpo": texto, "cabecalhos": cab, "logs": registo}
                )
            )
        # O controlo: identificadores que nao existem em tenant nenhum.
        controlo, _, texto_de_controlo = servidor.pedir(
            "POST",
            "/internal/event",
            json.dumps(_envelope(str(uuid.uuid4()), str(uuid.uuid4()))).encode(),
            dict(json_),
        )
        recusados = list(entrega.corpos)

        # A metade positiva: com a credencial, a rota **chega** a porta. Sem
        # isto, as afirmacoes acima passavam com uma rota que recusa tudo.
        positivo, _, texto_positivo = servidor.pedir(
            "POST",
            "/internal/event",
            json.dumps(_envelope(ctx.a.id, str(uuid.uuid4()))).encode(),
            {**json_, "x-kamba-interno": CREDENCIAL},
        )
        achados.extend(
            f"{ITEM_DO_EVENTO}: {fuga}"
            for fuga in ctx.oraculo.varrer_tudo(
                {"corpo": texto_positivo, "logs": registo}
            )
        )

    ctx.logs.extend(registo)
    achados.extend(_uniformidade(ITEM_DO_EVENTO, estados, (401,)))
    if len(corpos) > 1:
        achados.append(
            f"{ITEM_DO_EVENTO}: os tres ataques receberam corpos diferentes "
            f"({sorted(corpos)}). Um corpo que varie com o que se manda distingue "
            "o que existe do que nao existe."
        )
    if controlo not in estados or texto_de_controlo not in corpos:
        achados.append(
            f"{ITEM_DO_EVENTO}: os ataques com o que e de B deram {sorted(set(estados))} "
            f"e o controlo com identificadores inexistentes deu {controlo}, ou outro "
            "corpo. A diferenca e um oraculo de existencia."
        )
    if recusados:
        achados.append(
            f"{ITEM_DO_EVENTO}: a porta da entrega foi chamada {len(recusados)} "
            "vez(es) sem a credencial certa. A rota tem de recusar antes de ler o "
            "corpo."
        )
    if positivo != 200 or len(entrega.corpos) != len(recusados) + 1:
        achados.append(
            f"{ITEM_DO_EVENTO}: com a credencial certa a rota respondeu {positivo} e "
            f"a porta foi chamada {len(entrega.corpos) - len(recusados)} vez(es), e "
            "nao 200 e uma. O caso nao mediu que a rota chega a porta, so que recusa."
        )
    return achados


def atacar_sonda_e_metricas(ctx: Any) -> list[str]:
    """O X-01 da `/healthz` e da `/metrics` do IDX: respondem, e nada de B sai.

    **Conta antes de ler**, pela razao do `/metrics` do AGR: uma serie so
    aparece depois de escrita, e um oraculo sobre um corpo vazio nao mede nada.
    """
    _no_caminho()
    from kamba_core.idx.metricas import METRICAS  # noqa: PLC0415

    METRICAS.registar_reindexacao(0)
    registo: list[str] = []
    achados: list[str] = []
    with _Servidor(_EntregaRegistadora(), registo) as servidor:
        for item, caminho in ((ITEM_DA_SONDA, "/healthz"), (ITEM_DAS_METRICAS, "/metrics")):
            estado, cab, texto = servidor.pedir("GET", caminho)
            if estado != 200:
                achados.append(
                    f"{item}: respondeu {estado} e nao 200; o caso nao mediu o que "
                    "queria medir."
                )
            if caminho == "/metrics" and "# TYPE" not in texto:
                achados.append(
                    f"{item}: o corpo nao traz `# TYPE`, logo nao ha series e o "
                    "oraculo varreria o vazio."
                )
            achados.extend(
                f"{item}: {fuga}"
                for fuga in ctx.oraculo.varrer_tudo(
                    {"corpo": texto, "cabecalhos": cab, "logs": registo}
                )
            )
    ctx.logs.extend(registo)
    return achados
