"""O processo do IDX: a rota de entrega e o ciclo da reindexacao (KAM-194).

Um processo, duas tarefas, e as duas escrevem no `idx.search_doc`:

1. **`POST /internal/event`** — a entrega de um evento pela casca da fila
   (`packages/core-ts/src/eventos/ponte.ts`). A decisao esta em `entrega.py`;
   aqui so se le o pedido, se confere a credencial e se traduz a `Resposta` em
   HTTP. Serve tambem `/healthz` e `/metrics`.
2. **O ciclo da reindexacao** (KAM-062, `docs/tecnica/05` §4.4) — de
   `intervalo` em `intervalo` segundos, para cada *tenant* activo, corre o
   `consumidor.reindexar` ate ele devolver menos do que um lote: os documentos
   **visiveis** com `norm_versao` anterior a corrente reescrevem-se, `lote` de
   cada vez, uma transaccao por lote.

## Porque e que e a biblioteca padrao, e nao Starlette

O `kamba_core` nao tem dependencias (`libs/py-core/pyproject.toml`), e este
processo corre com a imagem do AGR, que traz o `pg8000`. A rota e uma; o
`ThreadingHTTPServer` serve-a com uma *thread* por pedido, e cada pedido abre e
fecha a sua ligacao — que e o que o `tenant_guard` exige (uma ligacao por
pedido). A casca entrega com concorrencia 1 por particao, pelo que dezasseis
pedidos e o ciclo sao o maximo de ligacoes abertas.

## Dois papeis, e o segundo so le uma coisa

As entregas e a reindexacao correm como **`kamba_app`** (`NOBYPASSRLS`), com o
contexto do *tenant* por transaccao. A **lista de *tenants* activos** nao se le
assim — a RLS de `platform.tenants` so mostra o do contexto —, e le-se como
**`kamba_batch`**, pelo `tenant_guard.tx_batch` com o nome de *job*
`idx_reindexacao`, que fica contado. E a unica leitura deste papel.

## O que este processo nunca faz

* nao regista o envelope, o `event_id`, o `tenant_id` nem o texto de um erro:
  regista o desfecho e o estado HTTP, que sao de lista fechada;
* nao serve metrica com etiqueta de *tenant*: o `idx_reindexed_total` e um
  contador sem etiquetas.
"""

from __future__ import annotations

import hmac
import json
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Final

from kamba_core import tenant_guard
from kamba_core.eventos.ligacao import ClienteDaLigacao
from kamba_core.health import healthz

from . import consumidor
from .entrega import EntregaAoIdx, Resposta
from .metricas import METRICAS, MetricasDoIdx

#: O nome do servico, no `/healthz` e no registo.
SERVICO: Final = "idx"
VERSAO: Final = "0.1.0"

#: A porta da rota. Tem de coincidir com o compose e com o alvo da casca.
VARIAVEL_DA_PORTA: Final = "IDX_PORT"
PORTA_POR_OMISSAO: Final = 8061

#: A rota de entrega, o cabecalho da credencial e o segredo que ele leva. O
#: segredo e **deste** servico e nao o `agr_internal_token`: uma credencial por
#: servico, porque quem a tem alcanca tudo o que o servico serve (a razao do
#: `com_internal_token`, `ops/secrets-inventory.yaml`).
CAMINHO_DO_EVENTO: Final = "/internal/event"
CABECALHO_INTERNO: Final = "x-kamba-interno"
SEGREDO_DA_API: Final = "idx_internal_token"

#: O maior corpo aceite, em bytes. Um envelope do catalogo cabe em poucos KiB;
#: 256 KiB e o tecto do `/internal/*` do AGR.
CORPO_MAXIMO: Final = 256 * 1024

#: Segundos entre voltas do ciclo de reindexacao. **Proposta**, calibrada na
#: medicao da pilha (alvo do KAM-062: 2 000 produtos de um *tenant* em <= 10
#: min). Uma volta corre ate cada *tenant* estar em dia; o intervalo e so a
#: espera entre voltas.
VARIAVEL_DO_INTERVALO: Final = "KAMBA_IDX_REINDEX_INTERVALO_S"
INTERVALO_POR_OMISSAO_S: Final = 60

#: Documentos por transaccao. **Proposta**, a do KAM-062.
VARIAVEL_DO_LOTE: Final = "KAMBA_IDX_REINDEX_LOTE"
LOTE_POR_OMISSAO: Final = consumidor.LOTE_DE_REINDEXACAO

#: O tecto de lotes por *tenant* numa volta. **Proposta**: 50 x 200 = 10 000
#: documentos. Nao e o alvo — e a rede contra um ciclo que nunca acaba (um
#: lexico que muda a cada lote volta a marcar o que acabou de escrever), que
#: segurava a ligacao e deixava os outros *tenants* a espera. O que fica por
#: escrever escreve-se na volta seguinte.
LOTES_POR_VOLTA: Final = 50

#: O nome do *job* do `kamba_batch`. Fica contado em `rls_batch_uso_total`.
JOB_DA_LISTA: Final = "idx_reindexacao"

#: Os *tenants* que podem ter documentos visiveis. Um suspenso ou encerrado
#: tem-nos todos invisiveis (o `visivel` junta o estado `ativo`), e o
#: `reindexar` so reescreve os visiveis.
SQL_TENANTS_ACTIVOS: Final = """
  SELECT id::text FROM platform.tenants WHERE estado = 'ativo' ORDER BY id
"""


def configuracao_inteira(
    ambiente: Any, nome: str, omissao: int, minimo: int = 1
) -> int:
    """Um inteiro positivo do ambiente, ou a omissao. Levanta se for invalido.

    Recusa em vez de corrigir: um `KAMBA_IDX_REINDEX_LOTE=0` lido como a
    omissao era uma configuracao que alguem escreveu e que nao manda nada.
    """
    bruto = (ambiente.get(nome) or "").strip()
    if not bruto:
        return omissao
    if not bruto.isdigit() or int(bruto) < minimo:
        raise ValueError(f"{nome} tem de ser um inteiro >= {minimo}")
    return int(bruto)


# ------------------------------------------------------------- a reindexacao


class Reindexacao:
    """O ciclo do `reindexar` do KAM-062, uma volta de cada vez."""

    __slots__ = ("_abrir_app", "_abrir_batch", "_lote", "_metricas")

    def __init__(
        self,
        abrir_app: Callable[[], Any],
        abrir_batch: Callable[[], Any],
        lote: int = LOTE_POR_OMISSAO,
        metricas: MetricasDoIdx = METRICAS,
    ) -> None:
        if isinstance(lote, bool) or not isinstance(lote, int) or lote < 1:
            raise ValueError("lote e um inteiro >= 1")
        self._abrir_app = abrir_app
        self._abrir_batch = abrir_batch
        self._lote = lote
        self._metricas = metricas

    def tenants(self) -> list[str]:
        ligacao = self._abrir_batch()
        try:
            with tenant_guard.tx_batch(ligacao, JOB_DA_LISTA) as cursor:
                cursor.execute(SQL_TENANTS_ACTIVOS)
                return [str(linha[0]) for linha in cursor.fetchall()]
        finally:
            ligacao.close()

    def do_tenant(self, tenant_id: str) -> int:
        """Reescreve os documentos marcados de um *tenant*, lote a lote.

        Para quando uma volta devolve **menos** do que um lote: a seguinte ja
        nao teria nada. Um lote cheio pede outra volta, e um documento que o
        `reindexar` esconde (oferta desaparecida) deixa de ser marcado — e por
        isso que o ciclo acaba.
        """
        total = 0
        ligacao = self._abrir_app()
        try:
            for _ in range(LOTES_POR_VOLTA):
                with tenant_guard.tx(ligacao, tenant_id):
                    escritos = consumidor.reindexar(
                        ClienteDaLigacao(ligacao), tenant_id, self._lote
                    )
                total += escritos
                if escritos < self._lote:
                    break
            return total
        finally:
            ligacao.close()

    def volta(self, ao_falhar: Callable[[BaseException], None] | None = None) -> int:
        """Uma volta por todos os *tenants* activos. Devolve quantos reescreveu.

        Conta **sempre**, mesmo zero: a serie existe a partir da primeira volta,
        e um painel que a nao visse nao distinguia «em dia» de «o ciclo nao
        corre».

        **Um *tenant* que falha nao trava os seguintes.** A lista vem por `id`,
        e uma excepcao a subir abortava a volta no primeiro *tenant* com uma
        falha persistente — os que vem depois dele nunca eram reindexados, volta
        apos volta. Cada falha vai ao `ao_falhar` e a volta segue; os documentos
        do que falhou ficam marcados para a seguinte. Achado da revisao
        adversarial.
        """
        total = 0
        for tenant in self.tenants():
            try:
                total += self.do_tenant(tenant)
            except Exception as erro:  # noqa: BLE001 — a volta segue
                if ao_falhar is not None:
                    ao_falhar(erro)
        self._metricas.registar_reindexacao(total)
        return total

    def correr(
        self,
        parar: threading.Event,
        intervalo_s: float,
        ao_falhar: Callable[[BaseException], None] | None = None,
    ) -> None:
        """Voltas de `intervalo_s` em `intervalo_s` segundos ate `parar`.

        Uma volta que falha (a base em baixo) nao mata o ciclo: espera o
        intervalo e tenta outra vez. Os documentos ficam marcados ate la — a
        marca e a `norm_versao` na base, e nao estado deste processo.
        """
        while not parar.is_set():
            try:
                self.volta(ao_falhar)
            except Exception as erro:  # noqa: BLE001 — o ciclo nao morre
                if ao_falhar is not None:
                    ao_falhar(erro)
            parar.wait(intervalo_s)


# ------------------------------------------------------------------- a rota


def tratador(
    entrega: EntregaAoIdx,
    credencial: Callable[[], str],
    metricas: MetricasDoIdx = METRICAS,
    ao_responder: Callable[[str, int], None] | None = None,
) -> type[BaseHTTPRequestHandler]:
    """A classe de pedido do `ThreadingHTTPServer`, com as portas ligadas.

    `credencial` e uma funcao e nao uma cadeia: o segredo roda, e um valor lido
    no arranque ficava a recusar a casca depois da rotacao.
    """

    class Tratador(BaseHTTPRequestHandler):
        server_version = "kamba-idx"
        sys_version = ""

        def log_message(self, formato: str, *args: Any) -> None:  # noqa: ARG002
            # O `BaseHTTPRequestHandler` escreve o caminho e o cliente em
            # `stderr`. Nao se escreve nada fora do `kamba_core.logger`.
            return

        def _json(self, estado: int, corpo: object, cabecalhos: dict[str, str] | None = None) -> None:
            dados = json.dumps(corpo).encode("utf-8")
            self.send_response(estado)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(dados)))
            for nome, valor in (cabecalhos or {}).items():
                self.send_header(nome, valor)
            self.end_headers()
            self.wfile.write(dados)

        def do_GET(self) -> None:  # noqa: N802 — nome da biblioteca padrao
            if self.path == "/healthz":
                self._json(200, healthz(SERVICO, VERSAO))
                return
            if self.path == "/metrics":
                dados = metricas.exposicao().encode("utf-8")
                self.send_response(200)
                self.send_header("content-type", "text/plain; version=0.0.4")
                self.send_header("content-length", str(len(dados)))
                self.end_headers()
                self.wfile.write(dados)
                return
            self._json(404, {"outcome": "rota_desconhecida"})

        def do_POST(self) -> None:  # noqa: N802 — nome da biblioteca padrao
            if self.path != CAMINHO_DO_EVENTO:
                self._json(404, {"outcome": "rota_desconhecida"})
                return
            resposta = self._entregar()
            cabecalhos = (
                {"Retry-After": str(resposta.retry_after)}
                if resposta.retry_after is not None
                else None
            )
            # Antes de responder, e nao depois: a casca le a resposta e pode
            # entregar o *job* seguinte antes de esta linha correr.
            if ao_responder is not None:
                ao_responder(resposta.outcome, resposta.estado)
            self._json(resposta.estado, resposta.corpo(), cabecalhos)

        def _entregar(self) -> Resposta:
            dado = self.headers.get(CABECALHO_INTERNO) or ""
            if not dado or not hmac.compare_digest(
                dado.encode("utf-8"), credencial().encode("utf-8")
            ):
                return Resposta(401, "nao_autorizado")
            try:
                tamanho = int(self.headers.get("content-length") or "0")
            except ValueError:
                return Resposta(400, "corpo_invalido", error_code="tamanho_invalido")
            if tamanho > CORPO_MAXIMO or tamanho < 0:
                return Resposta(400, "corpo_invalido", error_code="corpo_grande")
            try:
                corpo = json.loads(self.rfile.read(tamanho))
            except (ValueError, UnicodeDecodeError):
                return Resposta(400, "corpo_invalido", error_code="corpo_nao_e_json")
            try:
                return entrega.entregar(corpo)
            except Exception:  # noqa: BLE001 — a base em baixo: a fila repete
                # A ligacao nao abriu, ou a DLQ nao escreveu. Nada ficou
                # marcado (o `consumir` desfaz-se no erro), e o evento volta.
                return Resposta(503, "adiado", retry_after=5)

    return Tratador


def servidor(
    porta: int,
    entrega: EntregaAoIdx,
    credencial: Callable[[], str],
    anfitriao: str = "127.0.0.1",
    metricas: MetricasDoIdx = METRICAS,
    ao_responder: Callable[[str, int], None] | None = None,
) -> ThreadingHTTPServer:
    """O servidor, por arrancar (`serve_forever`). `porta = 0` escolhe uma livre."""
    servidor_http = ThreadingHTTPServer(
        (anfitriao, porta), tratador(entrega, credencial, metricas, ao_responder)
    )
    servidor_http.daemon_threads = True
    return servidor_http
