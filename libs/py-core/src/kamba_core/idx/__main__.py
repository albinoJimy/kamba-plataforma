"""`python -m kamba_core.idx` — o processo do IDX (KAM-194).

So ligacoes: le o ambiente, abre o cofre, constroi as portas e arranca a rota e
o ciclo. A decisao toda esta em `entrega.py` e `processo.py`, que se testam sem
rede nem base; este ficheiro fica fora da medicao do *gate* 4 como os outros
`__main__.py` (`ci/thresholds.yaml`).

Corre com a imagem do AGR (`services/agr/Dockerfile`), que traz o `pg8000` e o
`kamba_core` no `PYTHONPATH`, e e um servico de compose proprio — `idx` — como
cada processo do `worker-canal` e um servico com a mesma imagem.

Codigos de saida: 2 cofre ou configuracao, 0 paragem pedida.
"""

from __future__ import annotations

import os
import signal
import sys
import threading
from typing import Any, Final

from kamba_core.logger import instalar
from kamba_core.secrets import EnvSecretProvider, Secrets

from .entrega import EntregaAoIdx
from .processo import (
    INTERVALO_POR_OMISSAO_S,
    LOTE_POR_OMISSAO,
    PORTA_POR_OMISSAO,
    SEGREDO_DA_API,
    SERVICO,
    VARIAVEL_DA_PORTA,
    VARIAVEL_DO_INTERVALO,
    VARIAVEL_DO_LOTE,
    Reindexacao,
    configuracao_inteira,
    servidor,
)

#: As variaveis da base: as do AGR (`kamba_agr/ligacao.py`), com dois papeis.
VAR_HOST = "KAMBA_DB_HOST"
VAR_PORTA = "KAMBA_DB_PORT"
VAR_BASE = "KAMBA_DB_NAME"
#: `kamba_app` — as entregas e a reindexacao, com contexto de *tenant*.
VAR_SENHA_APP: Final = "KAMBA_SECRET_DB_APP_PASSWORD"
#: `kamba_batch` — so a lista de *tenants* activos (`processo.SQL_TENANTS_ACTIVOS`).
VAR_SENHA_BATCH: Final = "KAMBA_SECRET_DB_BATCH_PASSWORD"

#: Os dois papeis, e o que cada um faz. **As entregas e a reindexacao sao do
#: `kamba_app`** (`NOBYPASSRLS`): com o `kamba_batch` correriam na mesma — e sem
#: RLS nenhuma. Presos pelo `TestLigadores` da `test_idx_entrega.py`.
PAPEL_DA_ENTREGA = "kamba_app"
PAPEL_DA_LISTA = "kamba_batch"


class ConfiguracaoEmFalta(RuntimeError):
    """Falta uma variavel de ambiente. A mensagem diz qual; nunca um valor."""


def _exigir(ambiente: Any, nome: str) -> str:
    valor = (ambiente.get(nome) or "").strip()
    if not valor:
        raise ConfiguracaoEmFalta(f"a variavel de ambiente {nome} nao esta definida (ou esta vazia)")
    return valor


def _ligador(ambiente: Any, papel: str, var_senha: str, nome: str):
    def ligar() -> Any:
        import pg8000.dbapi

        porta = ambiente.get(VAR_PORTA, "5432")
        if not porta.isdigit():
            raise ConfiguracaoEmFalta(f"{VAR_PORTA} tem de ser um numero de porta")
        ligacao = pg8000.dbapi.connect(
            user=papel,
            password=_exigir(ambiente, var_senha),
            host=ambiente.get(VAR_HOST, "127.0.0.1"),
            port=int(porta),
            database=_exigir(ambiente, VAR_BASE),
            application_name=nome,
        )
        ligacao.autocommit = False
        return ligacao

    return ligar


def ligadores(ambiente: Any) -> tuple[Any, Any]:
    """`(abrir_app, abrir_batch)`: as duas fabricas de ligacoes, com o papel certo."""
    return (
        _ligador(ambiente, PAPEL_DA_ENTREGA, VAR_SENHA_APP, "kamba-idx:entrega"),
        _ligador(ambiente, PAPEL_DA_LISTA, VAR_SENHA_BATCH, "kamba-idx:lista"),
    )


def deve_registar(outcome: str, estado: int) -> bool:
    """O que vai a registo: o que nao e 200, **e** o que foi para a DLQ.

    Um `para_dlq` responde 200 — foi tratado, e a fila larga-o —, e um registo
    so do que nao e 200 deixava a DLQ do `idx` sem rasto nenhum no processo.
    Achado da revisao adversarial.
    """
    return estado != 200 or outcome == "para_dlq"


def main(ambiente: Any = None) -> int:
    ambiente = os.environ if ambiente is None else ambiente
    log = instalar(SERVICO)
    try:
        porta = configuracao_inteira(ambiente, VARIAVEL_DA_PORTA, PORTA_POR_OMISSAO)
        intervalo = configuracao_inteira(ambiente, VARIAVEL_DO_INTERVALO, INTERVALO_POR_OMISSAO_S)
        lote = configuracao_inteira(ambiente, VARIAVEL_DO_LOTE, LOTE_POR_OMISSAO)
        for nome in (VAR_BASE, VAR_SENHA_APP, VAR_SENHA_BATCH):
            _exigir(ambiente, nome)
    except (ValueError, ConfiguracaoEmFalta) as exc:
        log.excepcao(exc, "arranque_invalido")
        return 2
    try:
        segredos = Secrets.arrancar(
            servico=SERVICO,
            provider=EnvSecretProvider(ambiente),
            obrigatorios=[SEGREDO_DA_API],
        )
    except Exception as exc:  # noqa: BLE001 — qualquer falha de cofre aborta
        log.excepcao(exc, "cofre_indisponivel")
        return 2

    abrir_app, abrir_batch = ligadores(ambiente)
    entrega = EntregaAoIdx(abrir_app)
    reindexacao = Reindexacao(abrir_app, abrir_batch, lote)

    def ao_responder(outcome: str, estado: int) -> None:
        # O caminho feliz nao vai a registo: uma linha por evento enchia-o. O
        # estado vai no `error_code` (`http_503`), que e o campo da *allowlist*
        # (`docs/tecnica/08` §7.3) que o leva.
        if deve_registar(outcome, estado):
            log.warn(outcome=outcome, error_code=f"http_{estado}")

    http = servidor(
        porta,
        entrega,
        lambda: segredos.get(SEGREDO_DA_API),
        anfitriao=ambiente.get("HOST", "127.0.0.1"),
        ao_responder=ao_responder,
    )
    parar = threading.Event()
    ciclo = threading.Thread(
        target=reindexacao.correr,
        args=(parar, intervalo, lambda exc: log.excepcao(exc, "reindexacao_falhou")),
        name="idx-reindexacao",
        daemon=True,
    )

    def terminar(_sinal: int, _quadro: object) -> None:
        parar.set()
        threading.Thread(target=http.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, terminar)
    signal.signal(signal.SIGINT, terminar)
    ciclo.start()
    log.info(outcome="service_started")
    http.serve_forever()
    http.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
