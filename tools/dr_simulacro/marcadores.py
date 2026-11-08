"""O escritor de linhas-marcador a 1/s (KAM-085, criterio 1).

    python -m dr_simulacro.marcadores --host H --base B --saida /out/conf.csv \
        --parar /out/parar

Corre no contentor **condutor**, que nao e o *host* da base: quando o ensaio
mata o primario, a lista de confirmados sobrevive, e e ela que o RPO compara
com o que o restauro devolve.

Cada marcador e uma linha `seq,escrito_em` no ficheiro de saida, escrita **so
depois** de a base confirmar o *commit* e com o `escrito_em` que a base
devolveu no `RETURNING` (`clock_timestamp()`, o relogio do servidor). Escrever
antes da confirmacao era registar como confirmado o que pode nunca ter
chegado — e era essa a linha que o RPO usava como «ultimo confirmado».

## Um erro de ligacao repete o **mesmo** numero

Se o `INSERT` falha a meio, o *commit* pode ter acontecido sem a confirmacao
chegar. Passar ao numero seguinte deixava um buraco que o restauro nao teria
por culpa propria, e o `calculo.rpo` conta buracos como perda. Por isso a
proxima tentativa e o **mesmo** `seq`, com `ON CONFLICT DO NOTHING`; se o
conflito disser que ja la estava, le-se o `escrito_em` guardado e confirma-se
esse.
"""

from __future__ import annotations

import argparse
import os
import time
from datetime import datetime
from pathlib import Path

from .folha import formatar, ler_instante

SQL_TABELA = """
CREATE SCHEMA IF NOT EXISTS dr_simulacro;
CREATE TABLE IF NOT EXISTS dr_simulacro.marcador (
  seq        bigint PRIMARY KEY,
  escrito_em timestamptz NOT NULL DEFAULT clock_timestamp()
);
"""

SQL_INSERIR = (
    "INSERT INTO dr_simulacro.marcador (seq) VALUES (:seq) "
    "ON CONFLICT (seq) DO NOTHING RETURNING seq, escrito_em"
)
SQL_LER = "SELECT seq, escrito_em FROM dr_simulacro.marcador WHERE seq = :seq"


def escrever(ligar, saida: Path, *, parar, relogio=time.monotonic, dormir=time.sleep,
             periodo: float = 1.0, erros: Path | None = None, primeiro: int = 1) -> dict:
    """Escreve marcadores ate `parar()` dizer que sim. Devolve um resumo.

    `ligar()` devolve uma ligacao com `run(sql, **parametros) -> list[list]`
    (a forma do `pg8000.native`). O relogio e o `dormir` vem por parametro, para
    que o ensaio da cadencia e da repeticao do mesmo numero corra sem esperar.
    """
    ligacao = None
    seq = primeiro
    confirmados = falhas = 0
    proximo = relogio()
    while not parar():
        try:
            if ligacao is None:
                ligacao = ligar()
            linhas = ligacao.run(SQL_INSERIR, seq=seq)
            if not linhas:
                linhas = ligacao.run(SQL_LER, seq=seq)
            numero, escrito_em = linhas[0]
            with saida.open("a", encoding="utf-8", newline="\n") as ficheiro:
                ficheiro.write(f"{int(numero)},{formatar(escrito_em)}\n")
                ficheiro.flush()
                os.fsync(ficheiro.fileno())
            confirmados += 1
            seq += 1
        except Exception as erro:  # noqa: BLE001 — qualquer falha e «nao confirmado»
            falhas += 1
            ligacao = None
            if erros is not None:
                with erros.open("a", encoding="utf-8", newline="\n") as ficheiro:
                    ficheiro.write(f"{seq},{type(erro).__name__}\n")
        proximo += periodo
        espera = proximo - relogio()
        if espera > 0:
            dormir(espera)
        else:
            proximo = relogio()
    return {"confirmados": confirmados, "falhas": falhas, "proximo_seq": seq}


def ler_csv(texto: str) -> list[tuple[int, datetime]]:
    """`seq,instante` por linha, de um CSV de confirmados ou de um `COPY` restaurado."""
    resultado = []
    for linha in texto.splitlines():
        linha = linha.strip()
        if not linha:
            continue
        numero, instante = linha.split(",", 1)
        resultado.append((int(numero), ler_instante(instante.strip())))
    return resultado


def _ligar_pg8000(argumentos):  # pragma: no cover — so corre no condutor
    import pg8000.native

    return pg8000.native.Connection(
        user=argumentos.utilizador, password=os.environ["KAM085_PG_SENHA"],
        host=argumentos.host, port=argumentos.porta, database=argumentos.base,
        timeout=5,
    )


def main(argv: list[str] | None = None) -> int:  # pragma: no cover — idem
    analisador = argparse.ArgumentParser(prog="dr_simulacro.marcadores")
    analisador.add_argument("--host", required=True)
    analisador.add_argument("--porta", type=int, default=5432)
    analisador.add_argument("--base", required=True)
    analisador.add_argument("--utilizador", default="kamba")
    analisador.add_argument("--saida", type=Path, required=True)
    analisador.add_argument("--erros", type=Path)
    analisador.add_argument("--parar", type=Path, required=True,
                            help="o escritor para quando este ficheiro existir")
    analisador.add_argument("--primeiro", type=int, default=1)
    argumentos = analisador.parse_args(argv)
    resumo = escrever(lambda: _ligar_pg8000(argumentos), argumentos.saida,
                      parar=argumentos.parar.exists, erros=argumentos.erros,
                      primeiro=argumentos.primeiro)
    print(resumo, flush=True)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
