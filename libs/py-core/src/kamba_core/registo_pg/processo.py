"""O processo do recolector: a volta de leitura e a rota `/metrics` (KAM-225).

**Onde corre, e porque.** Na rede `ops`, ao lado do Prometheus, com o volume do
registo do PostgreSQL montado so de leitura (`docker-compose.prod.yml`, servico
`registo-pg`). Nao abre ligacao a base, nao tem credencial nenhuma, e nao sai
para fora: le ficheiros e serve um numero. Decisao do fundador de 2026-11-21
(opcao A do bloco do KAM-225): um recolector nosso, sem peca de terceiros nem
migracao.

**Falha alto.** Uma pasta que nao se le, ou sem nenhum `*.json` no arranque (o
`jsonlog` desligado), faz o processo sair com codigo 2; um erro de leitura a
meio, com 3. As duas acabam no reinicio do contentor e na sonda do `/healthz`:
um recolector que servisse zero sem ver o registo era a falha que este ticket
fecha, escrita ao contrario.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Final

from kamba_core.health import healthz

from .leitor import Seguidor, campos, e_recusa_no_tecto
from .metricas import METRICAS, MetricasDoRegistoPg

SERVICO: Final = "registo-pg"
VERSAO: Final = "0.1.0"

#: A porta da rota. Tem de coincidir com o compose e com o `prometheus.yml`.
VARIAVEL_DA_PORTA: Final = "REGISTO_PG_PORT"
PORTA_POR_OMISSAO: Final = 8225

#: A pasta do `jsonlog`, que e o `log_directory` do `postgres` no compose.
VARIAVEL_DA_PASTA: Final = "KAMBA_REGISTO_PG_DIR"
PASTA_POR_OMISSAO: Final = "/var/log/postgresql"

#: Segundos entre voltas. *Proposta*: a regra avalia de 30 em 30 s.
INTERVALO_S: Final = 1.0


def porta(ambiente: Any) -> int:
    """A porta do ambiente, ou a omissao. Levanta sem repetir o valor lido.

    Nao usa o `configuracao_inteira` do `idx`: importa-lo trazia o `idx` inteiro
    para um processo que se mede em MiB.
    """
    cru = (ambiente.get(VARIAVEL_DA_PORTA) or "").strip()
    if not cru:
        return PORTA_POR_OMISSAO
    if not cru.isdigit() or not 0 < int(cru) < 65536:
        raise ValueError(f"{VARIAVEL_DA_PORTA} tem de ser um numero de porta")
    return int(cru)


class RegistoIlegivel(RuntimeError):
    """A pasta do registo nao se le, ou nao tem o `jsonlog`. A mensagem diz qual."""


class Recolha:
    """Uma volta le as linhas novas e conta as recusas no tecto."""

    def __init__(self, pasta: Path, metricas: MetricasDoRegistoPg = METRICAS) -> None:
        try:
            self._seguidor = Seguidor(pasta)
            nomes = self._seguidor.nomes()
        except OSError as exc:
            raise RegistoIlegivel(f"a pasta do registo nao se le: {type(exc).__name__}") from exc
        if not nomes:
            raise RegistoIlegivel(
                "a pasta do registo nao tem nenhum *.json: o jsonlog do PostgreSQL esta desligado"
            )
        self._metricas = metricas

    def volta(self) -> int:
        """Le o que ha de novo; devolve quantas recusas contou nesta volta."""
        contadas = 0
        for linha, truncada in self._seguidor.linhas():
            if e_recusa_no_tecto(campos(linha, truncada)):
                self._metricas.contar()
                contadas += 1
        return contadas

    def correr(self, parar: threading.Event, intervalo: float = INTERVALO_S) -> None:
        """Voltas ate `parar`. Um erro de leitura **sobe**: quem chama sai."""
        while not parar.is_set():
            self.volta()
            parar.wait(intervalo)


def tratador(metricas: MetricasDoRegistoPg = METRICAS) -> type[BaseHTTPRequestHandler]:
    class Tratador(BaseHTTPRequestHandler):
        server_version = "kamba-registo-pg"
        sys_version = ""

        def log_message(self, formato: str, *args: Any) -> None:  # noqa: ARG002
            # O `BaseHTTPRequestHandler` escreve o caminho e o cliente em
            # `stderr`. Nao se escreve nada fora do `kamba_core.logger`.
            return

        def _enviar(self, estado: int, dados: bytes, tipo: str) -> None:
            self.send_response(estado)
            self.send_header("content-type", tipo)
            self.send_header("content-length", str(len(dados)))
            self.end_headers()
            self.wfile.write(dados)

        def do_GET(self) -> None:  # noqa: N802 — nome da biblioteca padrao
            if self.path == "/healthz":
                corpo = json.dumps(healthz(SERVICO, VERSAO)).encode("utf-8")
                self._enviar(200, corpo, "application/json")
            elif self.path == "/metrics":
                self._enviar(200, metricas.exposicao().encode("utf-8"), "text/plain; version=0.0.4")
            else:
                corpo = json.dumps({"outcome": "rota_desconhecida"}).encode("utf-8")
                self._enviar(404, corpo, "application/json")

    return Tratador


def servidor(
    porta: int, anfitriao: str = "127.0.0.1", metricas: MetricasDoRegistoPg = METRICAS
) -> ThreadingHTTPServer:
    """O servidor, por arrancar (`serve_forever`). `porta = 0` escolhe uma livre."""
    http = ThreadingHTTPServer((anfitriao, porta), tratador(metricas))
    http.daemon_threads = True
    return http


def correr_ate(parar: threading.Event, recolha: Recolha, ao_falhar: Callable[[Exception], None]) -> int:
    """A volta no fio de quem chama. 0 se parou a pedido, 3 se a leitura falhou."""
    try:
        recolha.correr(parar)
    except OSError as exc:
        ao_falhar(exc)
        return 3
    return 0
