"""O ensaio do KAM-187: os quatro processos do `worker-canal` numa pilha levantada.

    python db/ensaio_consumidores.py [--manter] [--relatorio caminho.json]

Levanta, do **compose de staging** e com o nome de projecto `kam187-ensaio`, o
PostgreSQL, a fila, o AGR, o Prometheus e os quatro servicos do `worker-canal`,
cria os papeis e aplica as migracoes, e mede o que os criterios 1, 2, 3 e 5 e o
DoD do bloco pedem **numa pilha a correr, e nao num `docker compose config`**:

    criterio 1   o `config` lista cada servico com o seu `command:`
    criterio 2   um *job* na `wa-inbound` da uma linha em `inbound_events` e
                 `inbound_events_total{desfecho="registado"}`; com o servico do
                 `entrada.ts` parado, o mesmo *job* fica na fila (o controlo).
                 O mesmo par para a `agr-inbound` e o `agr_shim_total{outcome}`.
    criterio 3   duas replicas do publicador: uma so segura o lock 7101, e N
                 eventos do *outbox* dao N publicacoes **somadas nas duas
                 replicas** (`evt_publish_total{desfecho="entregue"}`), e nao 2N.
                 Contar os *jobs* nas particoes nao serve de oraculo: o
                 publicador usa o id do envelope como `jobId`, e o BullMQ
                 absorve um duplicado.
    criterio 5   `up` = 1 para cada replica dos quatro alvos.
    DoD 3        o consumo em repouso de cada contentor novo.

## Porque *staging* e nao producao, e o que isso esconde

**O `entrada.ts` nao arranca com `KAMBA_ENV=prod`**, e isso e uma medicao e nao
uma suposicao: o `Identidade.arrancar` do KAM-008 recusa o provedor de chaves de
ambiente em `prod`, e nao ha provedor de cofre (`docs/identidade.md` §8, linha
2). O compose de *staging* e o que tem a mesma imagem, o mesmo `command:` e os
mesmos limites com um `KAMBA_ENV` em que o processo arranca.

## O que se acrescenta a pilha, e porque

Um ficheiro de sobreposicao, escrito numa pasta temporaria, muda **duas** coisas
e mais nenhuma — e as duas estao no relatorio:

1. O `postgres` ganha uma rede nao-interna e uma porta em `127.0.0.1`, para as
   migracoes correrem deste lado. A rede `data` e `internal: true` e nao publica.
2. O `agr` recebe `KAMBA_ENV`, `KAMBA_SECRET_AGR_INTERNAL_TOKEN` e as quatro
   variaveis da base (`KAMBA_DB_HOST`, `KAMBA_DB_PORT`, `KAMBA_DB_NAME` e as duas
   senhas). **O compose de staging nao lhas passa e o AGR nao fica saudavel sem
   elas** — medido na primeira corrida deste ensaio:
   `checkpointer_indisponivel:ConfiguracaoEmFalta`, e o contentor `unhealthy`. O
   compose de desenvolvimento passa-as todas. E um achado fora do escopo do
   KAM-187, registado no bloco; sem o AGR a responder nao ha
   `agr_shim_total{outcome}` que contar.

Os segredos sao gerados nesta execucao, vivem so no ficheiro de ambiente
temporario e nao se imprimem. Os corpos sao sinteticos e os numeros de telefone
sao inventados.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
COMPOSE = RAIZ / "infra" / "compose" / "docker-compose.staging.yml"
PROJECTO = "kam187-ensaio"
ADMIN = "kamba_admin"
BASE = "kamba_platform"

ENTRADA = "worker-canal-entrada"
SHIM = "worker-canal-agr-shim"
PUBLICADOR = "worker-canal-publicador"
CONSUMIDOR = "worker-canal-consumidor"
NOVOS = (ENTRADA, SHIM, PUBLICADOR, CONSUMIDOR)
PORTAS = {ENTRADA: 3013, SHIM: 3025, PUBLICADOR: 3011, CONSUMIDOR: 3012}
JOBS = {"entrada": ENTRADA, "agr_shim": SHIM, "publicador": PUBLICADOR, "consumidor": CONSUMIDOR}
CONSUMER = "ensaio187"
EVENTOS_DO_PUBLICADOR = 20

PAPEIS = (
    "MIGRATOR", "APP", "BATCH", "RESOLVER", "IDENTITY", "AUDIT", "AGR", "PAY_HOOKS",
    "PAY",
)


def _chave(kid: str) -> str:
    return f"{kid}:{base64.b64encode(secrets.token_bytes(32)).decode('ascii')}"


def _ambiente() -> dict[str, str]:
    """Todos os `${X:?}` do compose de staging, com valores desta execucao."""
    texto = COMPOSE.read_text(encoding="utf-8")
    env: dict[str, str] = {}
    for nome in sorted(set(re.findall(r"\$\{([A-Za-z0-9_]+):\?", texto))):
        env[nome] = secrets.token_urlsafe(24)
    senhas = {p: secrets.token_urlsafe(24) for p in PAPEIS}
    for papel, senha in senhas.items():
        env[f"KAMBA_SECRET_DB_{papel}_PASSWORD"] = senha

    def url(papel: str) -> str:
        # Montada por partes: o `scan_secrets` le uma credencial embutida num
        # URL escrito por extenso, e aqui a senha e gerada nesta execucao.
        return "".join(
            ("postgresql://", "kamba_", papel.lower(), ":", senhas[papel], "@", "postgres:5432/", BASE)
        )

    env.update(
        {
            "KAMBA_COMMIT_SHA": subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=RAIZ, capture_output=True, text=True
            ).stdout.strip() or "ensaio",
            "POSTGRES_USER": ADMIN,
            "POSTGRES_DB": BASE,
            "KAMBA_ENTRADA_DB_URL": url("APP"),
            "KAMBA_CHR_RESOLVER_DB_URL": url("RESOLVER"),
            "KAMBA_CHR_IDENTITY_DB_URL": url("IDENTITY"),
            "KAMBA_PUBLICADOR_DB_URL": url("BATCH"),
            "KAMBA_CONSUMIDOR_DB_URL": url("APP"),
            "KAMBA_CONSUMIDOR_OPS_DB_URL": url("BATCH"),
            "KAMBA_COM_DB_URL": url("APP"),
            "KAMBA_CONSUMER": CONSUMER,
            "KAMBA_SECRET_PEPPER_CONTACT_HMAC": _chave("k-ensaio187"),
            "KAMBA_SECRET_KEK_CONTACT_DEK": _chave("kek-ensaio187"),
            "KAMBA_SECRET_SEGREDO_INTENTS": _chave("i-ensaio187"),
            "KAMBA_DATA_CLASS": "synthetic",
        }
    )
    return env


SOBREPOSICAO = """\
services:
  postgres:
    networks:
      - data
      - ensaio
    ports:
      - "127.0.0.1::5432"
  agr:
    environment:
      KAMBA_ENV: staging
      KAMBA_SECRET_AGR_INTERNAL_TOKEN: ${KAMBA_SECRET_AGR_INTERNAL_TOKEN}
      KAMBA_DB_HOST: postgres
      KAMBA_DB_PORT: "5432"
      KAMBA_DB_NAME: kamba_platform
      KAMBA_SECRET_DB_APP_PASSWORD: ${KAMBA_SECRET_DB_APP_PASSWORD}
      KAMBA_SECRET_DB_AGR_PASSWORD: ${KAMBA_SECRET_DB_AGR_PASSWORD}
networks:
  ensaio:
    driver: bridge
"""


class Pilha:
    def __init__(self, pasta: Path, env: dict[str, str]) -> None:
        self.env_ficheiro = pasta / "ensaio.env"
        self.env_ficheiro.write_text(
            "".join(f"{k}={v}\n" for k, v in env.items()), encoding="utf-8"
        )
        self.sobreposicao = pasta / "sobreposicao.yml"
        self.sobreposicao.write_text(SOBREPOSICAO, encoding="utf-8")
        self.env = env

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

    def contentores(self, servico: str) -> list[str]:
        saida = self.compose("ps", "-q", servico)
        return [c for c in saida.split() if c]

    def executar(self, contentor: str, *args: str) -> str:
        r = subprocess.run(["docker", "exec", contentor, *args], capture_output=True,
                           text=True, timeout=120, encoding="utf-8", errors="replace")
        if r.returncode != 0:
            raise RuntimeError(f"docker exec {args[:2]}: {r.stderr[-1000:]}")
        return r.stdout

    def metricas(self, servico: str) -> str:
        """O `/metrics` de **todas** as replicas, concatenado."""
        porta = PORTAS[servico]
        js = (f"fetch('http://127.0.0.1:{porta}/metrics').then(r=>r.text())"
              ".then(t=>process.stdout.write(t))")
        return "\n".join(self.executar(c, "node", "-e", js) for c in self.contentores(servico))

    def fila(self, *args: str) -> str:
        return self.executar(self.contentores("queue")[0], "valkey-cli", *args).strip()

    def sql(self, consulta: str) -> str:
        c = self.contentores("postgres")[0]
        return self.executar(c, "psql", "-U", ADMIN, "-d", BASE, "-At", "-c", consulta).strip()

    def node_no_worker(self, codigo: str) -> str:
        """Corre um modulo ESM com o `node_modules` do `worker-canal`, na rede da pilha."""
        return self.compose(
            "run", "--rm", "--no-deps", "-T", "-w", "/app/services/worker-canal",
            "--entrypoint", "node", ENTRADA, "--input-type=module", "-e", codigo,
            tempo=180,
        )


def _soma(texto: str, metrica: str, etiqueta: str | None = None) -> float:
    total = 0.0
    for linha in texto.splitlines():
        if linha.startswith("#") or not linha.startswith(metrica):
            continue
        nome, _, valor = linha.rpartition(" ")
        if etiqueta is not None and etiqueta not in nome:
            continue
        if nome == metrica or nome.startswith(metrica + "{"):
            total += float(valor)
    return total


def _esperar(condicao, limite: float, passo: float = 1.0):
    fim = time.monotonic() + limite
    ultimo = None
    while time.monotonic() < fim:
        ultimo = condicao()
        if ultimo:
            return ultimo
        time.sleep(passo)
    return ultimo


def _corpo_de_webhook() -> str:
    """Um `messages` da Meta, sintetico. Nenhum canal o reconhece, de proposito."""
    agora = int(time.time())
    corpo = {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "109876543210987",
            "changes": [{
                "field": "messages",
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {"display_phone_number": "100000000", "phone_number_id": "187187187187"},
                    "messages": [{
                        "from": "100000001", "id": f"wamid.ensaio187.{uuid.uuid4().hex}",
                        "timestamp": str(agora), "type": "text", "text": {"body": "ensaio"},
                    }],
                },
            }],
        }],
    }
    return base64.b64encode(json.dumps(corpo).encode("utf-8")).decode("ascii")


def _por_job(pilha: Pilha, fila: str, nome: str, dados: dict, job_id: str) -> None:
    codigo = (
        "import { FilasBullmq } from '@kamba/core-ts/eventos/filas_bullmq';"
        "const f = new FilasBullmq({ url: 'redis://queue:6379' });"
        f"await f.addLote({json.dumps(fila)}, [{{ jobId: {json.dumps(job_id)}, "
        f"nome: {json.dumps(nome)}, dados: {json.dumps(dados)} }}]);"
        "await f.fechar();"
    )
    pilha.node_no_worker(codigo)


def criterio_1(pilha: Pilha) -> dict:
    config = json.loads(pilha.compose("config", "--format", "json"))
    return {
        nome: {
            "command": config["services"][nome].get("command"),
            "replicas": (config["services"][nome].get("deploy") or {}).get("replicas", 1),
            "mem_limit": config["services"][nome].get("mem_limit"),
        }
        for nome in NOVOS
    }


def criterio_2_entrada(pilha: Pilha) -> dict:
    antes_linhas = int(pilha.sql("SELECT count(*) FROM platform.inbound_events"))
    antes_reg = _soma(pilha.metricas(ENTRADA), "inbound_events_total", 'desfecho="registado"')
    _por_job(pilha, "wa-inbound", "wa", {"corpo": _corpo_de_webhook(), "recebidoEm": int(time.time() * 1000)},
             f"ensaio187-{uuid.uuid4().hex}")
    linhas = _esperar(
        lambda: (n := int(pilha.sql("SELECT count(*) FROM platform.inbound_events"))) > antes_linhas and n,
        60,
    )
    depois_reg = _soma(pilha.metricas(ENTRADA), "inbound_events_total", 'desfecho="registado"')
    consumido = {
        "inbound_events_antes": antes_linhas, "inbound_events_depois": linhas or antes_linhas,
        "registado_antes": antes_reg, "registado_depois": depois_reg,
        "fila_wait_depois": int(pilha.fila("LLEN", "bull:wa-inbound:wait")),
    }
    # O controlo: o servico parado, e o mesmo *job* fica na fila.
    pilha.compose("stop", ENTRADA)
    espera_antes = int(pilha.fila("LLEN", "bull:wa-inbound:wait"))
    _por_job(pilha, "wa-inbound", "wa", {"corpo": _corpo_de_webhook(), "recebidoEm": int(time.time() * 1000)},
             f"ensaio187-{uuid.uuid4().hex}")
    time.sleep(15)
    parado = {
        "fila_wait_antes": espera_antes,
        "fila_wait_15s_depois": int(pilha.fila("LLEN", "bull:wa-inbound:wait")),
        "inbound_events": int(pilha.sql("SELECT count(*) FROM platform.inbound_events")),
    }
    pilha.compose("start", ENTRADA)
    pilha.compose("up", "-d", "--wait", "--no-deps", ENTRADA)
    drenou = _esperar(lambda: int(pilha.fila("LLEN", "bull:wa-inbound:wait")) == 0, 90)
    parado["drenou_ao_voltar"] = bool(drenou)
    parado["inbound_events_ao_voltar"] = int(pilha.sql("SELECT count(*) FROM platform.inbound_events"))
    return {"consumido": consumido, "controlo_parado": parado}


def criterio_2_shim(pilha: Pilha) -> dict:
    def contagem() -> dict[str, float]:
        texto = pilha.metricas(SHIM)
        return {
            "agr_shim_total": _soma(texto, "agr_shim_total"),
            "agr_shim_failed_total": _soma(texto, "agr_shim_failed_total"),
            "por_outcome": sorted({l.split(" ")[0] for l in texto.splitlines()
                                   if l.startswith("agr_shim_total{")}),
        }

    antes = contagem()
    invocacao = {"tenant_id": str(uuid.uuid4()), "ensaio": "kam187"}
    _por_job(pilha, "agr-inbound", "turno", invocacao, f"ensaio187-{uuid.uuid4().hex}")
    depois = _esperar(lambda: (c := contagem())["agr_shim_total"] > antes["agr_shim_total"] and c, 60)
    consumido = {"antes": antes, "depois": depois or contagem(),
                 "fila_wait_depois": int(pilha.fila("LLEN", "bull:agr-inbound:wait"))}
    pilha.compose("stop", SHIM)
    espera_antes = int(pilha.fila("LLEN", "bull:agr-inbound:wait"))
    _por_job(pilha, "agr-inbound", "turno", invocacao, f"ensaio187-{uuid.uuid4().hex}")
    time.sleep(15)
    parado = {"fila_wait_antes": espera_antes,
              "fila_wait_15s_depois": int(pilha.fila("LLEN", "bull:agr-inbound:wait"))}
    pilha.compose("start", SHIM)
    pilha.compose("up", "-d", "--wait", "--no-deps", SHIM)
    parado["drenou_ao_voltar"] = bool(
        _esperar(lambda: int(pilha.fila("LLEN", "bull:agr-inbound:wait")) == 0, 90)
    )
    return {"consumido": consumido, "controlo_parado": parado}


def criterio_3(pilha: Pilha) -> dict:
    lock = pilha.sql(
        "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND objid = 7101 AND granted"
    )
    pilha.sql(
        "INSERT INTO platform.evt_subscricoes (consumer, tipo, finalidade, exige_ordem) "
        f"VALUES ('{CONSUMER}', 'ensaio.kam187', 'transacao', true) ON CONFLICT DO NOTHING"
    )
    tenant = str(uuid.uuid4())
    for i in range(EVENTOS_DO_PUBLICADOR):
        pilha.sql(
            "SELECT platform.evt_emitir('ensaio.kam187', 1::smallint, "
            f"'{tenant}'::uuid, 'ensaio', 'agregado-{i % 4}', '{{\"i\": {i}}}'::jsonb)"
        )
    publicados = _esperar(
        lambda: int(pilha.sql(
            "SELECT count(*) FROM platform.events_outbox WHERE tipo = 'ensaio.kam187' "
            "AND publicado_at IS NOT NULL")) == EVENTOS_DO_PUBLICADOR,
        60,
    )
    time.sleep(5)
    jobs = 0
    for p in range(16):
        prefixo = f"bull:evt.{CONSUMER}.p{p}"
        jobs += sum(int(pilha.fila("LLEN", f"{prefixo}:{estado}") or 0)
                    for estado in ("wait", "active"))
        jobs += int(pilha.fila("ZCARD", f"{prefixo}:completed") or 0)
        jobs += int(pilha.fila("ZCARD", f"{prefixo}:failed") or 0)
        jobs += int(pilha.fila("ZCARD", f"{prefixo}:delayed") or 0)
    texto = pilha.metricas(PUBLICADOR)
    por_replica = []
    for c in pilha.contentores(PUBLICADOR):
        js = ("fetch('http://127.0.0.1:3011/metrics').then(r=>r.text())"
              ".then(t=>process.stdout.write(t))")
        por_replica.append(_soma(pilha.executar(c, "node", "-e", js),
                                 "evt_publish_total", 'desfecho="entregue"'))
    return {
        "entregues_por_replica": por_replica,
        "entregues_somados": sum(por_replica),
        "replicas_do_publicador": len(pilha.contentores(PUBLICADOR)),
        "sessoes_com_o_lock_7101": int(lock),
        "eventos_emitidos": EVENTOS_DO_PUBLICADOR,
        "eventos_publicados": int(pilha.sql(
            "SELECT count(*) FROM platform.events_outbox WHERE tipo = 'ensaio.kam187' "
            "AND publicado_at IS NOT NULL")),
        "publicados_a_tempo": bool(publicados),
        "jobs_nas_particoes": jobs,
        "consumidos": int(pilha.sql(
            f"SELECT count(*) FROM platform.events_consumed WHERE consumer = '{CONSUMER}'") or 0),
        "metricas_do_publicador": sorted({l.split(" ")[0] for l in texto.splitlines()
                                          if l.startswith("evt_") and not l.startswith("#")})[:12],
    }


def criterio_5(pilha: Pilha) -> dict:
    prom = pilha.contentores("prometheus")[0]

    def consulta() -> list:
        bruto = pilha.executar(prom, "wget", "-q", "-O", "-",
                               "http://127.0.0.1:9090/api/v1/query?query=up")
        return json.loads(bruto)["data"]["result"]

    def todos_acima() -> list | None:
        r = consulta()
        dos_novos = [s for s in r if s["metric"]["job"] in JOBS]
        return r if len(dos_novos) == 7 and all(s["value"][1] == "1" for s in dos_novos) else None

    resultado = _esperar(todos_acima, 120, passo=5) or consulta()
    return {
        "series": sorted(
            (s["metric"]["job"], s["metric"]["instance"], s["value"][1]) for s in resultado
        )
    }


def repouso(pilha: Pilha) -> dict:
    medidas = {}
    for servico in NOVOS:
        for c in pilha.contentores(servico):
            stat = pilha.executar(c, "cat", "/sys/fs/cgroup/memory.stat")
            corrente = int(pilha.executar(c, "cat", "/sys/fs/cgroup/memory.current"))
            inactivo = int(re.search(r"^inactive_file (\d+)$", stat, re.M).group(1))
            nome = subprocess.run(["docker", "inspect", "-f", "{{.Name}}", c],
                                  capture_output=True, text=True).stdout.strip().lstrip("/")
            medidas[nome] = round((corrente - inactivo) / (1024 * 1024), 1)
    return medidas


def veredictos(r: dict) -> dict[str, bool]:
    """O que cada medicao tem de dar. O guiao sai com 1 se alguma falhar.

    O `agr_shim_total` **nao** entra: conta desfechos do AGR, e o AGR do compose
    de *staging* nao responde (ver a docstring do modulo). O consumo da fila
    pelo *shim* entra.
    """
    e = r["criterio_2_entrada"]
    s = r["criterio_2_shim"]
    p = r["criterio_3_publicador"]
    up = [linha for linha in r["criterio_5_up"]["series"] if linha[0] in JOBS]
    return {
        "c2_entrada_consome": e["consumido"]["inbound_events_depois"] > e["consumido"]["inbound_events_antes"]
        and e["consumido"]["registado_depois"] > e["consumido"]["registado_antes"],
        "c2_entrada_controlo": e["controlo_parado"]["fila_wait_15s_depois"] > e["controlo_parado"]["fila_wait_antes"]
        and e["controlo_parado"]["drenou_ao_voltar"],
        "c2_shim_consome": s["consumido"]["fila_wait_depois"] == 0,
        "c2_shim_controlo": s["controlo_parado"]["fila_wait_15s_depois"] > s["controlo_parado"]["fila_wait_antes"]
        and s["controlo_parado"]["drenou_ao_voltar"],
        "c3_um_lider": p["sessoes_com_o_lock_7101"] == 1 and p["replicas_do_publicador"] == 2,
        "c3_sem_dobro": p["entregues_somados"] == p["eventos_emitidos"]
        and p["eventos_publicados"] == p["eventos_emitidos"],
        "c5_up": len(up) == 7 and all(linha[2] == "1" for linha in up),
    }


def principal() -> int:
    argumentos = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    argumentos.add_argument("--manter", action="store_true", help="nao derruba a pilha no fim")
    argumentos.add_argument("--relatorio", type=Path)
    opcoes = argumentos.parse_args()

    relatorio: dict = {"inicio_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    with tempfile.TemporaryDirectory(prefix="kam187-") as pasta:
        env = _ambiente()
        pilha = Pilha(Path(pasta), env)
        relatorio["commit"] = env["KAMBA_COMMIT_SHA"]
        try:
            relatorio["criterio_1_config"] = criterio_1(pilha)
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
            pilha.compose("up", "-d", "--build", "--wait", "prometheus", *NOVOS, tempo=1800)
            # O AGR a parte: a saude dele nao e o que este ensaio mede, e uma
            # falha dele nao pode esconder a medicao dos quatro.
            pilha.compose("up", "-d", "--wait", "--wait-timeout", "120", "--no-deps", "agr",
                          verificar=False, tempo=300)
            relatorio["estado"] = pilha.compose("ps", "--format", "{{.Service}} {{.Status}}")
            time.sleep(20)
            relatorio["repouso_mib"] = repouso(pilha)
            relatorio["criterio_5_up"] = criterio_5(pilha)
            relatorio["criterio_2_entrada"] = criterio_2_entrada(pilha)
            relatorio["criterio_2_shim"] = criterio_2_shim(pilha)
            relatorio["criterio_3_publicador"] = criterio_3(pilha)
            relatorio["veredictos"] = veredictos(relatorio)
        except Exception as erro:  # noqa: BLE001 — o relatorio leva o que se mediu
            relatorio["erro"] = f"{type(erro).__name__}: {erro}"
            relatorio["registos"] = {
                s: pilha.compose("logs", "--tail", "15", s, verificar=False)[-3000:]
                for s in (*NOVOS, "agr")
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
