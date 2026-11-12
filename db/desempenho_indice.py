"""A medicao de latencia do indice (KAM-061, criterio 10): instrumento, fora do CI.

    python db/desempenho_indice.py [relatorio.json]

Levanta o PostgreSQL do *gate* (a mesma imagem, por *digest*), aplica os papeis e
as migracoes ate a cabeca, semeia **um tenant de 5 000 documentos sinteticos** —
e mais dois tenants com outros 5 000 cada, para que o filtro por tenant tenha o
que filtrar — e corre **500 execucoes** de cada modo, como `kamba_app`, com o
contexto do tenant e o limiar do `pg_trgm` em `SET LOCAL`, que e o caminho do
chamador do §6.2:

    lexical    idx.candidatos com `p_qvec` nulo            alvo p95 <= 80 ms
    hibrido    idx.candidatos com vector (excl. embedding) alvo p95 <= 120 ms
    resposta   kamba_core.idx.pesquisa.pesquisar, lexical  (criterio do epic: p95 <= 300 ms)

O relatorio leva os percentis e o **ambiente** (versoes do servidor e do
pgvector, a imagem, o sistema, os nucleos), que e a metade do criterio que
uma tabela de numeros sozinha nao cumpre.

**Porque nao e uma suite do `gate_bd.py`**, pela razao do `db/carga.py`: o
`SUITES` e o que o CI corre, e por um limiar de latencia num *gate* e decisao do
fundador. Isto mede; nao bloqueia nada.

**O que os numeros nao dizem.** A maquina e a de quem corre, com o Docker
Desktop e outros contentores a competir; o relogio e o do cliente (inclui a ida e
volta pela porta publicada), pelo que mede **por cima**. O catalogo e
sintetico — combinacoes de um vocabulario fixo — e a distribuicao real de nomes
de um catalogo angolano e NAO VERIFICADA. As 500 execucoes ciclam por 50
perguntas, com *typos* e termos inexistentes.
"""

from __future__ import annotations

import json
import os
import platform
import random
import signal
import statistics
import subprocess
import sys
import time
from pathlib import Path

DB = Path(__file__).resolve().parent
RAIZ = DB.parent
sys.path.insert(0, str(DB))
sys.path.insert(0, str(RAIZ / "libs" / "py-core" / "src"))

import gate_bd  # noqa: E402

#: Documentos por tenant (criterio 10).
DOCUMENTOS = 5_000
#: Execucoes por modo (criterio 10).
EXECUCOES = 500
#: Os alvos do criterio 10, em ms, e o da recuperacao total (epic, §2).
ALVOS = {"lexical": 80.0, "hibrido": 120.0, "resposta": 300.0}
#: A semente do gerador: a mesma corrida gera o mesmo catalogo e as mesmas perguntas.
SEMENTE = 61

MARCAS = ("nike", "adidas", "samsung", "lg", "tecno", "itel", "hisense", "puma",
          "philips", "binatone", "sumol", "compal", "nocal", "cuca", "dove", "nivea")
TIPOS = ("tenis", "sapatilha", "telemovel", "televisor", "frigorifico", "arca",
         "ventoinha", "ferro", "arroz", "feijao", "oleo", "sabao", "camisa",
         "calcas", "vestido", "bolsa", "relogio", "auscultadores", "carregador", "colchao")
ATRIBUTOS = ("branco", "preto", "azul", "vermelho", "grande", "pequeno", "inox",
             "duplo", "classico", "novo", "premium", "economico")
MEDIDAS = ("1 l", "5 kg", "25 kg", "250 l", "55 pol", "32 pol", "128 gb", "64 gb",
           "42", "40", "m", "xl")


def _nome(i: int) -> str:
    return " ".join(
        (
            TIPOS[i % len(TIPOS)],
            MARCAS[(i // len(TIPOS)) % len(MARCAS)],
            ATRIBUTOS[(i // 7) % len(ATRIBUTOS)],
            MEDIDAS[(i // 11) % len(MEDIDAS)],
        )
    )


def _perguntas(gerador: random.Random) -> list[str]:
    perguntas = []
    for _ in range(40):
        perguntas.append(f"{gerador.choice(TIPOS)} {gerador.choice(MARCAS)}")
    # *Typos* e um termo que nao existe, que e o D7.
    perguntas += ["niker", "samsumg televisor", "frigorifco lg", "telemovel xyzzy tecno",
                  "arroz 25 kg", "tenis nike branco 42", "colchao", "ventoinha philips",
                  "carregador itel", "relogio"]
    return perguntas


def _vector(gerador: random.Random) -> str:
    return "[" + ",".join(f"{gerador.uniform(-1, 1):.4f}" for _ in range(1024)) + "]"


def _percentis(amostras: list[float]) -> dict[str, float]:
    ordenadas = sorted(amostras)

    def p(q: float) -> float:
        # Posicao mais proxima, a mesma regra do `h6-export`.
        indice = max(0, min(len(ordenadas) - 1, round(q * len(ordenadas)) - 1))
        return round(ordenadas[indice], 2)

    return {
        "n": len(ordenadas),
        "p50": p(0.50),
        "p95": p(0.95),
        "p99": p(0.99),
        "max": round(ordenadas[-1], 2),
        "media": round(statistics.fmean(ordenadas), 2),
    }


def _semear(admin, tenant: str, embeddings: bool) -> None:
    cursor = admin.cursor()
    cursor.execute(
        "INSERT INTO idx.search_doc (tenant_id, product_ref, norm_versao, nome_norm, "
        " marca_canon, descr_norm, embedding) "
        "SELECT %s, 'sku-' || g, 1, n.nome, split_part(n.nome, ' ', 2), '', "
        "       CASE WHEN %s THEN "
        "         (SELECT array_agg(random() * 2 - 1)::real[] "
        "            FROM generate_series(1, 1024) WHERE g IS NOT NULL)::halfvec END "
        "  FROM generate_series(0, %s - 1) g, LATERAL (SELECT %s::text[] AS v) a, "
        "       LATERAL (SELECT a.v[(g %% %s) + 1] AS nome) n",
        (tenant, embeddings, DOCUMENTOS, [_nome(i) for i in range(DOCUMENTOS)], DOCUMENTOS),
    )
    cursor.execute(
        "INSERT INTO platform.offer_terms (tenant_id, sku, nome, preco_tipo, preco_minor, "
        " stock_modo, estado) "
        "SELECT %s, 'sku-' || g, 'Produto ' || g, 'fixo', 100000 + g, 'garantido', 'publicado' "
        "  FROM generate_series(0, %s - 1) g",
        (tenant, DOCUMENTOS),
    )
    cursor.execute("ANALYZE idx.search_doc")
    cursor.execute("ANALYZE platform.offer_terms")


def _dentro(relatorio: str | None) -> int:
    import bootstrap
    import indice
    import ligacao
    from tests import factories
    from tests.base import alembic_ok

    from kamba_core.idx import pesquisa

    bootstrap.aplicar()
    alembic_ok("upgrade", "head")
    admin = ligacao.ligar("admin")
    admin.autocommit = True
    cursor = admin.cursor()
    tenants = []
    for _ in range(3):
        tenant = factories.tenant(cursor)
        factories.aceitar_contratos_vigentes(cursor, tenant)
        cursor.execute("UPDATE platform.tenants SET estado = 'ativo' WHERE id = %s", (tenant,))
        tenants.append(tenant)
    inicio = time.perf_counter()
    for tenant in tenants:
        _semear(admin, tenant, embeddings=True)
    semeadura_s = round(time.perf_counter() - inicio, 1)

    gerador = random.Random(SEMENTE)
    perguntas = _perguntas(gerador)
    alvo = tenants[0]
    app = ligacao.ligar("app")
    medidas: dict[str, list[float]] = {"lexical": [], "hibrido": [], "resposta": []}
    vazias = {"lexical": 0, "hibrido": 0, "resposta": 0}
    vector_da_pergunta = _vector(gerador)
    from kamba_core.idx.texto import consulta

    servidor: dict[str, list[float]] = {"lexical": [], "hibrido": []}
    planos: dict[str, object] = {}
    for modo in ("lexical", "hibrido"):
        for i in range(EXECUCOES):
            pergunta = consulta(perguntas[i % len(perguntas)])
            argumentos = (alvo, pergunta.q_norm, pergunta.q_or,
                          vector_da_pergunta if modo == "hibrido" else None)
            c = app.cursor()
            t0 = time.perf_counter()
            c.execute("SELECT set_config('app.tenant_id', %s, true)", (alvo,))
            c.execute(pesquisa.SQL_LIMIAR, (str(indice.LIMIAR_DE_PALAVRA),))
            c.execute(
                "SELECT count(*) FROM idx.candidatos(%s, %s, %s, %s::halfvec)", argumentos
            )
            n = c.fetchone()[0]
            app.rollback()
            medidas[modo].append((time.perf_counter() - t0) * 1000)
            vazias[modo] += n == 0
            # O mesmo, medido pelo servidor: o `Execution Time` do `EXPLAIN
            # ANALYZE` nao tem a ida e volta pela porta publicada.
            c = app.cursor()
            c.execute("SELECT set_config('app.tenant_id', %s, true)", (alvo,))
            c.execute(pesquisa.SQL_LIMIAR, (str(indice.LIMIAR_DE_PALAVRA),))
            c.execute(
                "EXPLAIN (ANALYZE, FORMAT JSON) "
                "SELECT count(*) FROM idx.candidatos(%s, %s, %s, %s::halfvec)", argumentos
            )
            plano = c.fetchone()[0]
            plano = json.loads(plano) if isinstance(plano, str) else plano
            app.rollback()
            servidor[modo].append(float(plano[0]["Execution Time"]))
            planos.setdefault(modo, plano[0]["Plan"])
    for i in range(EXECUCOES):
        t0 = time.perf_counter()
        linhas = pesquisa.pesquisar(app, alvo, perguntas[i % len(perguntas)])
        medidas["resposta"].append((time.perf_counter() - t0) * 1000)
        vazias["resposta"] += not linhas

    cursor.execute("SELECT version()")
    versao = cursor.fetchone()[0]
    cursor.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
    pgvector = cursor.fetchone()[0]
    cursor.execute(
        "SELECT count(*) FROM pg_indexes WHERE schemaname = 'idx' AND indexdef ~* '(hnsw|ivfflat)'"
    )
    ann = cursor.fetchone()[0]
    resultado = {
        "ticket": "KAM-061",
        "criterio": 10,
        "documentos_por_tenant": DOCUMENTOS,
        "tenants": len(tenants),
        "execucoes_por_modo": EXECUCOES,
        "perguntas_distintas": len(perguntas),
        "semente": SEMENTE,
        "semeadura_s": semeadura_s,
        "indices_ann": ann,
        "servidor": {
            modo: {**_percentis(amostras), "alvo_p95_ms": ALVOS[modo],
                   "dentro_do_alvo": _percentis(amostras)["p95"] <= ALVOS[modo]}
            for modo, amostras in servidor.items()
        },
        "modos": {
            modo: {**_percentis(amostras), "alvo_p95_ms": ALVOS[modo],
                   "dentro_do_alvo": _percentis(amostras)["p95"] <= ALVOS[modo],
                   "respostas_vazias": vazias[modo]}
            for modo, amostras in medidas.items()
        },
        "ambiente": {
            "servidor": versao,
            "pgvector": pgvector,
            "imagem": gate_bd.IMAGEM,
            "sistema": platform.platform(),
            "python": platform.python_version(),
            "nucleos": os.cpu_count(),
            "relogio": "cliente, por execucao, inclui a ida e volta pela porta publicada",
        },
    }
    texto = json.dumps(resultado, indent=2, ensure_ascii=False)
    print(texto)
    if relatorio:
        Path(relatorio).write_text(texto + "\n", encoding="utf-8")
    app.close()
    admin.close()
    if relatorio:
        Path(relatorio).with_suffix(".planos.json").write_text(
            json.dumps(planos, indent=1), encoding="utf-8"
        )
    return 0 if all(m["dentro_do_alvo"] for m in resultado["modos"].values()) else 1


def _correr(ambiente: dict[str, str], _suite: str) -> int:
    argumentos = [sys.executable, str(Path(__file__).resolve()), "--dentro"]
    if os.environ.get("KAMBA_IDX_RELATORIO"):
        argumentos.append(os.environ["KAMBA_IDX_RELATORIO"])
    return subprocess.run(argumentos, cwd=DB, env=ambiente, timeout=3600).returncode


def main(argv: list[str]) -> int:
    if argv and argv[0] == "--dentro":
        return _dentro(argv[1] if len(argv) > 1 else None)
    if len(argv) > 1:
        print(__doc__, file=sys.stderr)
        return 2
    if argv:
        os.environ["KAMBA_IDX_RELATORIO"] = str(Path(argv[0]).resolve())
    for sinal in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sinal, gate_bd._sair_com_limpeza)
    return gate_bd.com_contentor("desempenho_indice", com_fila=False, correr=_correr)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
