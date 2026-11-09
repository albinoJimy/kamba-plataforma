"""O *outbox* e dois consumidores, para o cenario B (KAM-085, criterio 2).

    python -m dr_simulacro.eventos produzir --host H --base B --tenant T \
        --externos /out/externos.log --parar /out/parar
    python -m dr_simulacro.eventos retomar  ...   (so publica e consome)

Corre no contentor condutor contra as tabelas **reais** do esquema
(`platform.events_outbox`, `platform.events_consumed`, `platform.evt_emitir`,
das revisoes 0004 e 0005). O publicador e os consumidores **nao** sao os de
producao — esses sao TypeScript com BullMQ, e o ensaio nao levanta a pilha —:
sao a mesma regra escrita em SQL, e o que se mede e a propriedade da regra
depois de um PITR, nao o codigo do publicador.

## Os dois consumidores, e porque sao dois

- **interno** — o efeito e uma linha em `dr_simulacro.efeito`, na **mesma
  transaccao** que a marca em `events_consumed` (a regra do KAM-006). Depois de
  um PITR, o efeito e a marca voltam atras **juntos**, pelo que repetir o evento
  produz o efeito uma vez.
- **externo** — o efeito sai da base (uma mensagem a Meta, um pedido ao
  facilitador): aqui, uma linha num ficheiro **fora** da base, escrita antes de
  a marca entrar. Depois de um PITR o efeito **nao** volta atras e a marca
  volta, pelo que repetir o evento repete o efeito.

O `dr_simulacro.efeito` nao tem chave unica de proposito: e o instrumento que
mostra um duplicado, e uma restricao escondia-o num erro.
"""

from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

from .folha import formatar

TIPO = "dr.simulacro_encomenda"
INTERNO = "dr_interno"
EXTERNO = "dr_externo"

SQL_TABELAS = """
CREATE SCHEMA IF NOT EXISTS dr_simulacro;
CREATE TABLE IF NOT EXISTS dr_simulacro.encomenda (
  n           bigint PRIMARY KEY,
  total_minor bigint NOT NULL,
  criada_em   timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS dr_simulacro.efeito (
  event_id  uuid NOT NULL,
  feito_em  timestamptz NOT NULL DEFAULT clock_timestamp()
);
"""

SQL_PRODUZIR = (
    "SELECT platform.evt_emitir(:tipo, 1::smallint, CAST(:tenant AS uuid), "
    "'encomenda', CAST(:n AS text), jsonb_build_object('n', CAST(:n AS bigint)))"
)
SQL_PENDENTES = (
    "SELECT id, event_id::text, tenant_id::text, agregado_tipo, agregado_id, agregado_seq "
    "FROM platform.events_outbox WHERE publicado_at IS NULL AND tipo = :tipo "
    "ORDER BY id LIMIT 200"
)
SQL_MARCAR = (
    "INSERT INTO platform.events_consumed "
    "(consumer, event_id, tenant_id, agregado_tipo, agregado_id, agregado_seq) "
    "VALUES (:consumer, CAST(:event_id AS uuid), CAST(:tenant AS uuid), :atipo, :aid, :aseq) "
    "ON CONFLICT DO NOTHING RETURNING event_id"
)
SQL_JA_CONSUMIDO = (
    "SELECT 1 FROM platform.events_consumed "
    "WHERE consumer = :consumer AND event_id = CAST(:event_id AS uuid)"
)


def produzir(ligacao, n: int, tenant: str) -> None:
    """A encomenda e o evento na mesma transaccao (ADR-009)."""
    ligacao.run("BEGIN")
    try:
        ligacao.run(
            "INSERT INTO dr_simulacro.encomenda (n, total_minor) VALUES (:n, :t)",
            n=n, t=1000 + n,
        )
        ligacao.run(SQL_PRODUZIR, tipo=TIPO, tenant=tenant, n=n)
        ligacao.run("COMMIT")
    except Exception:
        ligacao.run("ROLLBACK")
        raise


def _parametros(evento) -> dict:
    _, event_id, tenant, atipo, aid, aseq = evento
    return {"event_id": event_id, "tenant": tenant, "atipo": atipo, "aid": aid, "aseq": aseq}


def consumir_interno(ligacao, evento) -> bool:
    """A marca e o efeito na mesma transaccao. Devolve se produziu efeito."""
    ligacao.run("BEGIN")
    try:
        marcado = ligacao.run(SQL_MARCAR, consumer=INTERNO, **_parametros(evento))
        if marcado:
            ligacao.run(
                "INSERT INTO dr_simulacro.efeito (event_id) VALUES (CAST(:e AS uuid))",
                e=evento[1],
            )
        ligacao.run("COMMIT")
    except Exception:
        ligacao.run("ROLLBACK")
        raise
    return bool(marcado)


def consumir_externo(ligacao, evento, externos: Path, relogio) -> bool:
    """O efeito sai da base **antes** da marca: e o *at-least-once* real."""
    if ligacao.run(SQL_JA_CONSUMIDO, consumer=EXTERNO, event_id=evento[1]):
        return False
    with externos.open("a", encoding="utf-8", newline="\n") as ficheiro:
        ficheiro.write(f"{evento[1]},{formatar(relogio())}\n")
        ficheiro.flush()
        os.fsync(ficheiro.fileno())
    ligacao.run(SQL_MARCAR, consumer=EXTERNO, **_parametros(evento))
    return True


def publicar(ligacao, externos: Path, relogio) -> int:
    """Entrega cada pendente aos dois consumidores e marca-o publicado."""
    pendentes = ligacao.run(SQL_PENDENTES, tipo=TIPO)
    for evento in pendentes:
        consumir_interno(ligacao, evento)
        consumir_externo(ligacao, evento, externos, relogio)
        ligacao.run(
            "UPDATE platform.events_outbox SET publicado_at = clock_timestamp() WHERE id = :id",
            id=evento[0],
        )
    return len(pendentes)


def correr(ligar, *, modo: str, tenant: str, externos: Path, parar, relogio,
           dormir=time.sleep, periodo: float = 1.0, primeiro: int = 1) -> dict:
    """`produzir`: um evento por periodo e publica; `retomar`: so publica ate esvaziar."""
    ligacao = ligar()
    n = primeiro
    produzidos = publicados = 0
    while not parar():
        if modo == "produzir":
            produzir(ligacao, n, tenant)
            produzidos += 1
            n += 1
        entregues = publicar(ligacao, externos, relogio)
        publicados += entregues
        if modo == "retomar" and entregues == 0:
            break
        dormir(periodo)
    return {"produzidos": produzidos, "publicados": publicados, "proximo_n": n}


def main(argv: list[str] | None = None) -> int:  # pragma: no cover — so no condutor
    from datetime import datetime, timezone

    import pg8000.native

    analisador = argparse.ArgumentParser(prog="dr_simulacro.eventos")
    analisador.add_argument("modo", choices=("produzir", "retomar"))
    analisador.add_argument("--host", required=True)
    analisador.add_argument("--porta", type=int, default=5432)
    analisador.add_argument("--base", required=True)
    analisador.add_argument("--utilizador", default="kamba")
    analisador.add_argument("--tenant", required=True)
    analisador.add_argument("--externos", type=Path, required=True)
    analisador.add_argument("--parar", type=Path, required=True)
    analisador.add_argument("--primeiro", type=int, default=1)
    argumentos = analisador.parse_args(argv)

    def ligar():
        return pg8000.native.Connection(
            user=argumentos.utilizador, password=os.environ["KAM085_PG_SENHA"],
            host=argumentos.host, port=argumentos.porta, database=argumentos.base,
            timeout=5,
        )

    try:
        resumo = correr(ligar, modo=argumentos.modo, tenant=argumentos.tenant,
                        externos=argumentos.externos, parar=argumentos.parar.exists,
                        relogio=lambda: datetime.now(timezone.utc),
                        primeiro=argumentos.primeiro)
    except Exception as erro:  # noqa: BLE001 — o primario morreu: e o que se espera
        print({"interrompido": type(erro).__name__}, flush=True)
        return 0
    print(resumo, flush=True)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
