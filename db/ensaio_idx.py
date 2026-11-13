"""O ensaio do KAM-194: a ponte fila -> consumidor Python numa pilha levantada.

    python db/ensaio_idx.py [--manter] [--relatorio caminho.json] [--amostras N]

No molde do `db/ensaio_consumidores.py` (KAM-187), e reutilizando o ambiente
dele: levanta, do **compose de staging** e com o nome de projecto
`kam194-ensaio`, o PostgreSQL, a fila, o publicador, o processo do IDX
(`python -m kamba_core.idx`) e a casca `worker-canal-ponte-idx`, cria os papeis,
aplica as migracoes — com a revisao de dados das subscricoes — e mede:

    frescura do produto   N tenants activos, uma oferta publicada cada, N
                          `catalog.product_changed` emitidos de rajada; a
                          latencia de cada um e `search_doc.atualizado_at -
                          events_log.ocorrido_em`, lida na base. p95 contra 30 s
                          (criterio 9 do KAM-061).
    frescura do tenant    os mesmos N suspensos, N `tenant.suspended`; a
                          latencia e o `atualizado_at` do documento que passou a
                          `visivel = false`. p95 contra 30 s.
    o controlo            com a casca parada, um `catalog.product_changed` fica
                          na fila (`bull:evt.idx.p<n>:wait`) e nao chega ao
                          indice nem ao `events_consumed`; com a casca de volta,
                          chega.
    a reindexacao         2 000 ofertas publicadas de um tenant, com os
                          documentos escritos numa versao anterior a corrente; o
                          tempo ate o ciclo os ter reescrito todos, contra 10 min
                          (KAM-062), e o `idx_reindexed_total` do processo.

**A latencia le-se da base, e nao de um relogio deste lado.** O `ocorrido_em`
e o `now()` da transaccao que emitiu e o `atualizado_at` e o `now()` da que
escreveu o documento: os dois sao o relogio do mesmo servidor, e o `docker exec`
de cada sondagem nao entra na conta.

Os segredos sao gerados nesta execucao e nao se imprimem; os dados sao
sinteticos.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ensaio_consumidores import ADMIN, BASE, COMPOSE, RAIZ, _ambiente, _esperar  # noqa: E402

PROJECTO = "kam194-ensaio"
IDX = "idx"
PONTE = "worker-canal-ponte-idx"
PUBLICADOR = "worker-canal-publicador"
SERVICOS = (PUBLICADOR, IDX, PONTE)
ALVO_P95_S = 30.0
ALVO_REINDEXACAO_S = 600.0
DOCUMENTOS_A_REINDEXAR = 2000

SOBREPOSICAO = """\
services:
  postgres:
    networks:
      - data
      - ensaio
    ports:
      - "127.0.0.1::5432"
networks:
  ensaio:
    driver: bridge
"""


class Pilha:
    def __init__(self, pasta: Path, env: dict[str, str]) -> None:
        self.env_ficheiro = pasta / "ensaio.env"
        self.env_ficheiro.write_text("".join(f"{k}={v}\n" for k, v in env.items()), encoding="utf-8")
        self.sobreposicao = pasta / "sobreposicao.yml"
        self.sobreposicao.write_text(SOBREPOSICAO, encoding="utf-8")

    def compose(self, *args: str, verificar: bool = True, tempo: float = 900) -> str:
        comando = [
            "docker", "compose", "-p", PROJECTO, "--env-file", str(self.env_ficheiro),
            "-f", str(COMPOSE), "-f", str(self.sobreposicao), *args,
        ]
        r = subprocess.run(comando, capture_output=True, text=True, timeout=tempo,
                           encoding="utf-8", errors="replace")
        if verificar and r.returncode != 0:
            raise RuntimeError(f"{' '.join(args[:3])}: {r.stderr[-2000:]}")
        return r.stdout

    def contentor(self, servico: str) -> str:
        return self.compose("ps", "-q", servico).split()[0]

    def executar(self, contentor: str, *args: str) -> str:
        r = subprocess.run(["docker", "exec", contentor, *args], capture_output=True,
                           text=True, timeout=180, encoding="utf-8", errors="replace")
        if r.returncode != 0:
            raise RuntimeError(f"docker exec {args[:2]}: {r.stderr[-1000:]}")
        return r.stdout

    def sql(self, consulta: str) -> str:
        return self.executar(self.contentor("postgres"), "psql", "-U", ADMIN, "-d", BASE,
                             "-v", "ON_ERROR_STOP=1", "-At", "-c", consulta).strip()

    def fila(self, *args: str) -> str:
        return self.executar(self.contentor("queue"), "valkey-cli", *args).strip()

    def metricas_do_idx(self) -> str:
        codigo = ("import urllib.request,sys;"
                  "sys.stdout.write(urllib.request.urlopen('http://127.0.0.1:8061/metrics').read().decode())")
        return self.executar(self.contentor(IDX), "python", "-c", codigo)


def _p95(valores: list[float]) -> float:
    ordenados = sorted(valores)
    return ordenados[max(0, -(-95 * len(ordenados) // 100) - 1)]


def _tenant(pilha: Pilha, nome: str) -> str:
    return pilha.sql(
        "INSERT INTO platform.tenants (tipo, nome, estado) "
        f"VALUES ('pme', '{nome}', 'ativo') RETURNING id"
    ).splitlines()[0]


def _oferta(pilha: Pilha, tenant: str, sku: str) -> None:
    pilha.sql(
        "INSERT INTO platform.offer_terms (tenant_id, sku, nome, preco_tipo, preco_minor, "
        "stock_modo, estado) VALUES "
        f"('{tenant}', '{sku}', 'Arroz agulha ensaio', 'fixo', 1250000, 'garantido', 'publicado')"
    )


def _emitir(pilha: Pilha, tipo: str, tenant: str, agregado_tipo: str, agregado_id: str, payload: dict) -> None:
    pilha.sql(
        f"SELECT platform.evt_emitir('{tipo}', 1::smallint, '{tenant}'::uuid, "
        f"'{agregado_tipo}', '{agregado_id}', '{json.dumps(payload)}'::jsonb)"
    )


def _na_fila_do_idx(pilha: Pilha) -> int:
    return sum(int(pilha.fila("LLEN", f"bull:evt.idx.p{p}:wait") or 0) for p in range(16))


def frescura(pilha: Pilha, amostras: int) -> dict:
    tenants = [_tenant(pilha, f"ensaio194-{i}") for i in range(amostras)]
    for i, tenant in enumerate(tenants):
        _oferta(pilha, tenant, f"ensaio-sku-{i}")
    for i, tenant in enumerate(tenants):
        _emitir(pilha, "catalog.product_changed", tenant, "product", f"ensaio-sku-{i}",
                {"sku": f"ensaio-sku-{i}", "estado": "publicado"})
    lista = "', '".join(tenants)
    escritos = _esperar(
        lambda: int(pilha.sql(f"SELECT count(*) FROM idx.search_doc WHERE visivel "
                              f"AND tenant_id IN ('{lista}')")) == amostras, 180)
    produto = [
        float(x) for x in pilha.sql(
            "SELECT extract(epoch FROM d.atualizado_at - l.ocorrido_em) "
            "  FROM idx.search_doc d JOIN platform.events_log l "
            "    ON l.tenant_id = d.tenant_id AND l.tipo = 'catalog.product_changed' "
            "   AND l.envelope->'payload'->>'sku' = d.product_ref "
            f" WHERE d.tenant_id IN ('{lista}')").splitlines() if x
    ]
    for tenant in tenants:
        pilha.sql(f"UPDATE platform.tenants SET estado = 'suspenso' WHERE id = '{tenant}'")
        _emitir(pilha, "tenant.suspended", tenant, "tenant", tenant, {"motivo": "ensaio"})
    escondidos = _esperar(
        lambda: int(pilha.sql(f"SELECT count(*) FROM idx.search_doc WHERE NOT visivel "
                              f"AND tenant_id IN ('{lista}')")) == amostras, 180)
    tenant_lat = [
        float(x) for x in pilha.sql(
            "SELECT extract(epoch FROM d.atualizado_at - l.ocorrido_em) "
            "  FROM idx.search_doc d JOIN platform.events_log l "
            "    ON l.tenant_id = d.tenant_id AND l.tipo = 'tenant.suspended' "
            f" WHERE d.tenant_id IN ('{lista}') AND NOT d.visivel").splitlines() if x
    ]
    return {
        "amostras": amostras,
        "produto_escrito_a_tempo": bool(escritos),
        "produto_latencias_s": sorted(round(v, 3) for v in produto),
        "produto_p95_s": round(_p95(produto), 3) if produto else None,
        "tenant_escondido_a_tempo": bool(escondidos),
        "tenant_latencias_s": sorted(round(v, 3) for v in tenant_lat),
        "tenant_p95_s": round(_p95(tenant_lat), 3) if tenant_lat else None,
        "consumidos_pelo_idx": int(pilha.sql(
            "SELECT count(*) FROM platform.events_consumed WHERE consumer = 'idx'")),
        "dlq_do_idx": int(pilha.sql(
            "SELECT count(*) FROM platform.events_dlq WHERE consumer = 'idx'")),
    }


def controlo(pilha: Pilha) -> dict:
    pilha.compose("stop", PONTE)
    tenant = _tenant(pilha, "ensaio194-controlo")
    _oferta(pilha, tenant, "ensaio-controlo")
    antes = _na_fila_do_idx(pilha)
    _emitir(pilha, "catalog.product_changed", tenant, "product", "ensaio-controlo",
            {"sku": "ensaio-controlo", "estado": "publicado"})
    enfileirado = _esperar(lambda: _na_fila_do_idx(pilha) > antes, 60)
    time.sleep(15)
    sem_casca = {
        "na_fila": _na_fila_do_idx(pilha),
        "documentos": int(pilha.sql(f"SELECT count(*) FROM idx.search_doc WHERE tenant_id = '{tenant}'")),
        "consumidos": int(pilha.sql(
            "SELECT count(*) FROM platform.events_consumed c JOIN platform.events_log l "
            f"ON l.event_id = c.event_id WHERE c.consumer = 'idx' AND l.tenant_id = '{tenant}'")),
    }
    pilha.compose("start", PONTE)
    chegou = _esperar(lambda: int(pilha.sql(
        f"SELECT count(*) FROM idx.search_doc WHERE visivel AND tenant_id = '{tenant}'")) == 1, 120)
    return {
        "enfileirado_com_a_casca_parada": bool(enfileirado),
        "sem_casca": sem_casca,
        "com_a_casca_de_volta_chegou": bool(chegou),
        "na_fila_depois": _na_fila_do_idx(pilha),
    }


def reindexacao(pilha: Pilha) -> dict:
    tenant = _tenant(pilha, "ensaio194-reindexacao")
    pilha.sql(
        "INSERT INTO platform.offer_terms (tenant_id, sku, nome, preco_tipo, preco_minor, "
        "stock_modo, estado) "
        f"SELECT '{tenant}', 'r-' || g, 'Produto ensaio ' || g, 'fixo', 1250000, 'garantido', "
        f"'publicado' FROM generate_series(1, {DOCUMENTOS_A_REINDEXAR}) g"
    )
    versao = int(pilha.sql(
        "SELECT COALESCE(max(versao) FILTER (WHERE afecta_indice), 1) FROM idx.norm_versao"))
    pilha.sql(
        "INSERT INTO idx.search_doc (tenant_id, product_ref, norm_versao, nome_norm, visivel) "
        f"SELECT '{tenant}', 'r-' || g, {versao - 1}, 'produto ensaio ' || g, true "
        f"FROM generate_series(1, {DOCUMENTOS_A_REINDEXAR}) g"
    )
    inicio = time.monotonic()
    em_dia = _esperar(lambda: int(pilha.sql(
        f"SELECT count(*) FROM idx.search_doc WHERE tenant_id = '{tenant}' "
        f"AND norm_versao < {versao}")) == 0, ALVO_REINDEXACAO_S + 120, passo=5)
    decorrido = time.monotonic() - inicio
    metricas = pilha.metricas_do_idx()
    reindexados = [l for l in metricas.splitlines() if l.startswith("idx_reindexed_total")]
    return {
        "documentos": DOCUMENTOS_A_REINDEXAR,
        "versao_corrente": versao,
        "em_dia": bool(em_dia),
        "segundos": round(decorrido, 1),
        "nota": "o tempo inclui ate um intervalo do ciclo (KAMBA_IDX_REINDEX_INTERVALO_S) de espera antes da primeira volta",
        "idx_reindexed_total": reindexados,
        "por_reescrever": int(pilha.sql(
            f"SELECT count(*) FROM idx.search_doc WHERE tenant_id = '{tenant}' AND norm_versao < {versao}")),
    }


def veredictos(r: dict) -> dict[str, bool]:
    f, c, x = r.get("frescura", {}), r.get("controlo", {}), r.get("reindexacao", {})
    return {
        "produto_p95_ate_30s": f.get("produto_p95_s") is not None and f["produto_p95_s"] <= ALVO_P95_S
        and len(f.get("produto_latencias_s", [])) == f.get("amostras"),
        "tenant_p95_ate_30s": f.get("tenant_p95_s") is not None and f["tenant_p95_s"] <= ALVO_P95_S
        and len(f.get("tenant_latencias_s", [])) == f.get("amostras"),
        "sem_dlq": f.get("dlq_do_idx") == 0,
        "controlo_fica_na_fila": bool(c.get("enfileirado_com_a_casca_parada"))
        and c.get("sem_casca", {}).get("documentos") == 0
        and c.get("sem_casca", {}).get("consumidos") == 0,
        "controlo_recupera": bool(c.get("com_a_casca_de_volta_chegou")),
        "reindexacao_2000_ate_10min": bool(x.get("em_dia")) and x.get("segundos", 1e9) <= ALVO_REINDEXACAO_S,
    }


def principal() -> int:
    argumentos = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    argumentos.add_argument("--manter", action="store_true", help="nao derruba a pilha no fim")
    argumentos.add_argument("--relatorio", type=Path)
    argumentos.add_argument("--amostras", type=int, default=20)
    opcoes = argumentos.parse_args()

    relatorio: dict = {"inicio_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    with tempfile.TemporaryDirectory(prefix="kam194-") as pasta:
        env = _ambiente()
        env["KAMBA_SECRET_IDX_INTERNAL_TOKEN"] = env.get("KAMBA_SECRET_IDX_INTERNAL_TOKEN") or uuid.uuid4().hex
        pilha = Pilha(Path(pasta), env)
        relatorio["commit"] = env["KAMBA_COMMIT_SHA"]
        try:
            pilha.compose("up", "-d", "--wait", "postgres", "queue")
            porta = pilha.compose("port", "postgres", "5432").strip().rsplit(":", 1)[1]
            amb = dict(os.environ)
            amb.update(env)
            amb.update({"KAMBA_DB_HOST": "127.0.0.1", "KAMBA_DB_PORT": porta,
                        "KAMBA_DB_NAME": BASE, "POSTGRES_PASSWORD": env["POSTGRES_PASSWORD"]})
            time.sleep(5)
            for comando in (
                [sys.executable, "bootstrap.py"],
                [sys.executable, "-m", "alembic", "-c", "migrations/alembic.ini", "upgrade", "head"],
            ):
                r = subprocess.run(comando, cwd=RAIZ / "db", env=amb, capture_output=True, text=True)
                if r.returncode != 0:
                    raise RuntimeError(f"{comando[1]}: {r.stderr[-2000:]}")
            relatorio["subscricoes_do_idx"] = pilha.sql(
                "SELECT consumer || ' ' || tipo FROM platform.evt_subscricoes "
                "WHERE consumer = 'idx' ORDER BY tipo").splitlines()
            pilha.compose("up", "-d", "--build", "--wait", "--no-deps", *SERVICOS, tempo=1800)
            relatorio["estado"] = pilha.compose("ps", "--format", "{{.Service}} {{.Status}}")
            relatorio["frescura"] = frescura(pilha, opcoes.amostras)
            relatorio["controlo"] = controlo(pilha)
            relatorio["reindexacao"] = reindexacao(pilha)
            relatorio["veredictos"] = veredictos(relatorio)
        except Exception as erro:  # noqa: BLE001 — o relatorio leva o que se mediu
            relatorio["erro"] = f"{type(erro).__name__}: {erro}"
            relatorio["registos"] = {
                s: pilha.compose("logs", "--tail", "20", s, verificar=False)[-3000:] for s in SERVICOS
            }
        finally:
            relatorio["fim_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            if not opcoes.manter:
                pilha.compose("down", "-v", "--remove-orphans", verificar=False)
    texto = json.dumps(relatorio, indent=2, ensure_ascii=False)
    if opcoes.relatorio:
        opcoes.relatorio.write_text(texto, encoding="utf-8")
    print(texto)
    falhados = [k for k, ok in relatorio.get("veredictos", {}).items() if not ok]
    return 1 if "erro" in relatorio or falhados else 0


if __name__ == "__main__":
    sys.exit(principal())
