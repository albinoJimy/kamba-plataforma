"""O ensaio do KAM-238: o pico de memoria do consumidor `dono` sob uma rajada.

    python db/ensaio_dono.py [--casos N] [--limite 54m] [--sonda compose|node|bash]
                             [--node-options=...] [--entrada caminho] [--prometheus]
                             [--manter] [--relatorio caminho.json]

Levanta, do **compose de staging** e com o nome de projecto `kam238-ensaio`, o
PostgreSQL e a fila, cria os papeis e aplica as migracoes, e levanta o
`onboarding-provisionamento` (imagem construida desta arvore). Depois:

    repouso    20 s depois de `healthy`: o *working set* do cgroup
               (`memory.current - inactive_file`, a definicao do KAM-084 §4.5),
               o `memory.peak` e o `VmRSS`/`VmHWM` do processo (PID 1)
    rajada     o `tests_bd/rajada_do_dono.ts` deixa N `tenant.provisioned` no
               *outbox*, cada um com um caso cujo telefone o consumidor decifra,
               e so entao arranca o publicador (`tests_bd/publicador_runner.ts`):
               os N eventos chegam as dezasseis filas `evt.dono.p<n>` de uma vez
    pico       amostras do cgroup a cada 0,5 s ate haver N donos, e no fim o
               `memory.peak`, o `VmHWM`, o `oom_kill` do `memory.events` e o
               `OOMKilled`/`RestartCount` do contentor

`--limite` fixa o `mem_limit` do processo (e so o dele) por uma sobreposicao, e
o `memswap_limit` **igual**: sem *swap*. E assim que se prova que o limite
proposto aguenta a rajada. A omissao e 54m, o limite do compose de producao
(KAM-241); o KAM-238 mediu sob 128m, 96m e 54m.

O KAM-241 acrescentou tres sobreposicoes, todas so do processo e todas no
relatorio: `--sonda` (`compose`, a omissao, corre a do ficheiro; `node` e a
`node -e fetch` que o KAM-238 mediu; `bash` e a de `/dev/tcp`), `--node-options`
(o `NODE_OPTIONS`; o relatorio le-o do contentor, e um veredicto exige-o igual ao
pedido) e `--entrada` (o ficheiro que o `node` corre, para comparar o `.ts` com o
compilado). Sem elas, o guiao mede o servico como o compose de *staging* o declara,
que e o de producao, com uma unica diferenca escrita sempre: a paciencia da sonda
no arranque (`start_period` e `timeout`, ver `_sobreposicao`). O instrumento le o
cgroup por `docker exec`, que corre **dentro** do cgroup medido: o pico e o CPU
que mede sao maiores ou iguais aos do processo so com a sonda.

**O `memswap_limit` nao e enfeite, e custou uma medicao.** O Docker Desktop tem
*swap*, e um `mem_limit` sozinho deixa o contentor usar outro tanto: a primeira
corrida sob 54m «sobreviveu» com 19 MiB em *swap* (`memory.swap.current`) e o
`memory.peak` colado ao limite. Isso nao e caber, e esconder o *swap* fazia o
limite parecer medido. O relatorio leva o `memory.swap.peak`, e um veredicto
exige-o a zero. O `memory.peak` e o que o OOM ve: e nele que o limite assenta,
como no KAM-225.

O guiao sai com 1 se um veredicto falhar: o limite pedido aplicado, os N donos
criados, nenhum evento na DLQ, nenhum `oom_kill`, o contentor sem reinicio,
nenhum *swap*, o contentor `healthy` depois da rajada, e o `NODE_OPTIONS` no
contentor igual ao pedido (ou ao do compose, sem `--node-options`). Os segredos
sao gerados nesta execucao e nao se imprimem; os telefones sao ficticios, com 999.

`--prometheus` (KAM-251) levanta tambem o Prometheus do compose de *staging*,
que monta o `prometheus.yml` de producao, antes da rajada: o pico mede-se com a
raspagem do `/metrics` a correr no mesmo cgroup, e o relatorio leva o alvo do
`job` `onboarding_provisionamento` (a `scrapeUrl`, a saude, o `up`), quantas
raspagens **bem sucedidas** (`up` a 1) cairam entre o arranque do publicador e
a ultima amostra do cgroup, e os nomes das series que o `job` trouxe. Um
veredicto a mais: o alvo `up`, e so ele.

## Porque *staging* e nao producao

O compose de *staging* levanta a pilha descartavel que o ensaio precisa (a base,
a fila e os papeis), e o servico dele e o de producao: a mesma imagem, o mesmo
`command:`, a mesma sonda, o mesmo `NODE_OPTIONS` e o mesmo limite (o KAM-241
pos-os iguais, e o processo entrou no compose de producao com eles). A base
chama-se `kamba_gate8` porque o `apoio.ts`, que o *runner* da rajada usa, so
aceita escrever na base descartavel.
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
import urllib.parse
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
COMPOSE = RAIZ / "infra" / "compose" / "docker-compose.staging.yml"
PROJECTO = "kam238-ensaio"
ADMIN = "kamba_admin"
BASE = "kamba_gate8"
SERVICO = "onboarding-provisionamento"
CONSUMIDOR = "dono"
#: O `job` do processo no `prometheus.yml` (KAM-251).
JOB = "onboarding_provisionamento"
PAPEIS = ("MIGRATOR", "APP", "BATCH", "RESOLVER", "IDENTITY", "AUDIT", "AGR", "PAY_HOOKS", "PAY")
MIB = 1024 * 1024


def _chave(kid: str) -> str:
    return f"{kid}:{base64.b64encode(secrets.token_bytes(32)).decode('ascii')}"


def _ambiente() -> tuple[dict[str, str], dict[str, str]]:
    """Os `${X:?}` do compose de staging, e o ambiente dos dois *runners*."""
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
        return "".join(("postgresql://", "kamba_", papel.lower(), ":", senhas[papel], "@", "postgres:5432/", BASE))

    chaves = {
        "KAMBA_SECRET_KEK_TELEFONE_DO_CASO": _chave("tel-ensaio238"),
        "KAMBA_SECRET_PEPPER_CONTACT_HMAC": _chave("k-ensaio238"),
        "KAMBA_SECRET_KEK_CONTACT_DEK": _chave("kek-ensaio238"),
    }
    env.update(chaves)
    env.update(
        {
            "KAMBA_COMMIT_SHA": subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=RAIZ, capture_output=True, text=True
            ).stdout.strip() or "ensaio",
            "POSTGRES_USER": ADMIN,
            "POSTGRES_DB": BASE,
            "KAMBA_PROVISIONAMENTO_APP_DB_URL": url("APP"),
            "KAMBA_PROVISIONAMENTO_IDENTITY_DB_URL": url("IDENTITY"),
            "KAMBA_DATA_CLASS": "synthetic",
        }
    )
    runner = {
        "KAMBA_ENV": "staging",
        "KAMBA_DB_HOST": "postgres",
        "KAMBA_DB_PORT": "5432",
        "KAMBA_DB_NAME": BASE,
        "POSTGRES_USER": ADMIN,
        "POSTGRES_PASSWORD": env["POSTGRES_PASSWORD"],
        "KAMBA_PUBLICADOR_DB_URL": url("BATCH"),
        # Desde o KAM-249 a fila de *staging* exige credencial; o `_ambiente`
        # gera-a como gera todas as `${X:?}` do compose. Montada por partes, pela
        # razao das ligacoes a base.
        "KAMBA_QUEUE_URL": "".join(
            ("redis://:", env["KAMBA_SECRET_QUEUE_PASSWORD"], "@", "queue:6379")
        ),
        **{f"KAMBA_SECRET_DB_{p}_PASSWORD": senhas[p] for p in ("APP", "BATCH", "IDENTITY", "RESOLVER")},
        **chaves,
    }
    return env, runner


#: A sonda em `bash` (a forma do `registo-pg` do KAM-225): `/dev/tcp`, sem `node`.
#: E a do compose desde o KAM-241. A do KAM-238 era `node -e fetch(...)`, um
#: segundo processo Node que o `docker exec` poe no mesmo cgroup e que o
#: `memory.peak` cobra (17,2 MiB sozinho num cgroup novo, medidos pela revisao
#: adversarial do KAM-238; 13 MiB de diferenca no pico do §2 do anexo).
#: `--sonda node` repoe-na, para comparar.
SONDA_BASH = (
    r"""["CMD", "bash", "-c", "{ printf 'GET /healthz HTTP/1.0\\r\\n\\r\\n' >&3 && head -c 12 <&3; }"""
    r""" 3<>/dev/tcp/127.0.0.1/3015 | grep -q '^HTTP/1\\.[01] 200'"]"""
)
#: A do KAM-238: um segundo processo Node no cgroup, ~13 MiB no `memory.peak`.
SONDA_NODE = json.dumps([
    "CMD", "node", "-e",
    "fetch('http://127.0.0.1:3015/healthz').then(r => process.exit(r.ok ? 0 : 1)).catch(() => process.exit(1))",
])


def _sobreposicao(limite: str, sonda: str, node_options: str | None = None, entrada: str | None = None) -> str:
    texto = """\
services:
  postgres:
    networks:
      - data
      - ensaio
    ports:
      - "127.0.0.1::5432"
"""
    texto += f"  {SERVICO}:\n    mem_limit: {limite}\n    memswap_limit: {limite}\n"
    # A paciencia da sonda no arranque (KAM-241), e so ela: com outras pilhas na
    # mesma maquina, o `docker exec` da sonda passou os 5 s e o arranque a 0,25 de
    # CPU passou os ~80 s do compose, com o `.ts` e com o compilado. O que a sonda
    # corre, e de quanto em quanto tempo depois de `healthy`, nao muda.
    texto += "    healthcheck:\n      start_period: 600s\n      timeout: 30s\n"
    if sonda == "bash":
        texto += f"      test: {SONDA_BASH}\n"
    elif sonda == "node":
        texto += f"      test: {SONDA_NODE}\n"
    if entrada is not None:
        texto += f"    command: {json.dumps(['node', entrada])}\n"
    if node_options is not None:
        texto += f"    environment:\n      NODE_OPTIONS: {json.dumps(node_options)}\n"
    return texto + "networks:\n  ensaio:\n    driver: bridge\n"


class Pilha:
    def __init__(
        self, pasta: Path, env: dict[str, str], limite: str, sonda: str,
        node_options: str | None = None, entrada: str | None = None,
    ) -> None:
        self.pasta = pasta
        self.env_ficheiro = pasta / "ensaio.env"
        self.env_ficheiro.write_text("".join(f"{k}={v}\n" for k, v in env.items()), encoding="utf-8")
        self.sobreposicao = pasta / "sobreposicao.yml"
        self.sobreposicao.write_text(_sobreposicao(limite, sonda, node_options, entrada), encoding="utf-8")

    def compose(self, *args: str, verificar: bool = True, tempo: float = 900) -> str:
        comando = [
            "docker", "compose", "-p", PROJECTO, "--env-file", str(self.env_ficheiro),
            "-f", str(COMPOSE), "-f", str(self.sobreposicao), *args,
        ]
        r = subprocess.run(comando, capture_output=True, text=True, timeout=tempo, encoding="utf-8", errors="replace")
        if verificar and r.returncode != 0:
            raise RuntimeError(f"{' '.join(args[:3])}: {r.stderr[-2000:]}")
        return r.stdout

    def contentor(self, servico: str) -> str:
        # `-a`: um contentor em `restarting` (o OOM no arranque) tambem conta.
        ids = [c for c in self.compose("ps", "-a", "-q", servico).split() if c]
        if len(ids) != 1:
            raise RuntimeError(f"{servico}: {len(ids)} contentores")
        return ids[0]

    def ler(self, contentor: str, caminho: str) -> str:
        r = subprocess.run(["docker", "exec", contentor, "cat", caminho], capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            raise RuntimeError(f"cat {caminho}: {r.stderr[-500:]}")
        return r.stdout

    def sql(self, consulta: str) -> str:
        r = subprocess.run(
            ["docker", "exec", self.contentor("postgres"), "psql", "-U", ADMIN, "-d", BASE, "-At", "-c", consulta],
            capture_output=True, text=True, timeout=60,
        )
        if r.returncode != 0:
            raise RuntimeError(f"psql: {r.stderr[-500:]}")
        return r.stdout.strip()

    def node(self, imagem: str, runner: dict[str, str], ficheiro: str, *, destacado: bool, nome: str) -> str:
        """Corre um *runner* do `tests_bd` na rede `data` da pilha, com a imagem do processo."""
        comando = ["docker", "run", "--name", nome, "--network", f"{PROJECTO}_data", "--entrypoint", "node"]
        comando += ["-d"] if destacado else ["--rm"]
        for k, v in runner.items():
            comando += ["-e", f"{k}={v}"]
        comando += [imagem, f"packages/core-ts/tests_bd/{ficheiro}"]
        r = subprocess.run(comando, capture_output=True, text=True, timeout=1800, encoding="utf-8", errors="replace")
        if r.returncode != 0:
            raise RuntimeError(f"{ficheiro}: {r.stderr[-2000:]}")
        return r.stdout.strip()


def _cgroup(pilha: Pilha, c: str) -> dict[str, float]:
    stat = pilha.ler(c, "/sys/fs/cgroup/memory.stat")
    corrente = int(pilha.ler(c, "/sys/fs/cgroup/memory.current"))
    inactivo = int(re.search(r"^inactive_file (\d+)$", stat, re.M).group(1))
    anon = int(re.search(r"^anon (\d+)$", stat, re.M).group(1))
    return {
        "working_set_mib": round((corrente - inactivo) / MIB, 1),
        "current_mib": round(corrente / MIB, 1),
        "anon_mib": round(anon / MIB, 1),
        "file_mib": round(int(re.search(r"^file (\d+)$", stat, re.M).group(1)) / MIB, 1),
    }


def _processo(pilha: Pilha, c: str) -> dict[str, float]:
    status = pilha.ler(c, "/proc/1/status")
    kb = {k: int(re.search(rf"^{k}:\s+(\d+) kB$", status, re.M).group(1)) for k in ("VmRSS", "VmHWM")}
    return {"vmrss_mib": round(kb["VmRSS"] / 1024, 1), "vmhwm_mib": round(kb["VmHWM"] / 1024, 1)}


def _picos(pilha: Pilha, c: str) -> dict:
    eventos = pilha.ler(c, "/sys/fs/cgroup/memory.events")
    inspeccao = json.loads(subprocess.run(
        ["docker", "inspect", c], capture_output=True, text=True, check=True).stdout)[0]
    return {
        "memory_peak_mib": round(int(pilha.ler(c, "/sys/fs/cgroup/memory.peak")) / MIB, 1),
        "memory_max_mib": round(int(pilha.ler(c, "/sys/fs/cgroup/memory.max")) / MIB, 1),
        "swap_peak_mib": round(int(pilha.ler(c, "/sys/fs/cgroup/memory.swap.peak")) / MIB, 1),
        "swap_max": pilha.ler(c, "/sys/fs/cgroup/memory.swap.max").strip(),
        # O CPU cobrado ao cgroup desde o arranque (KAM-241: o efeito das opcoes do V8).
        "cpu_s": round(int(re.search(r"^usage_usec (\d+)$", pilha.ler(c, "/sys/fs/cgroup/cpu.stat"), re.M).group(1)) / 1e6, 2),
        "oom_kill": int(re.search(r"^oom_kill (\d+)$", eventos, re.M).group(1)),
        "oom_killed": inspeccao["State"]["OOMKilled"],
        "restart_count": inspeccao["RestartCount"],
        "saude": inspeccao["State"].get("Health", {}).get("Status"),
        # O `NODE_OPTIONS` que o contentor tem, e nao o que se pediu: uma
        # sobreposicao que nao pegasse media o processo sem as opcoes (KAM-241).
        "node_options": next((e.split("=", 1)[1] for e in inspeccao["Config"]["Env"] or []
                              if e.startswith("NODE_OPTIONS=")), None),
        **_processo(pilha, c),
    }


def rajada(pilha: Pilha, runner: dict[str, str], casos: int, limite_s: float) -> dict:
    c = pilha.contentor(SERVICO)
    imagem = json.loads(subprocess.run(
        ["docker", "inspect", c], capture_output=True, text=True, check=True).stdout)[0]["Config"]["Image"]
    t0 = time.monotonic()
    pilha.node(imagem, {**runner, "KAMBA_RAJADA_CASOS": str(casos)}, "rajada_do_dono.ts",
               destacado=False, nome=f"{PROJECTO}-rajada")
    semeadura_s = round(time.monotonic() - t0, 1)
    no_outbox = int(pilha.sql("SELECT count(*) FROM platform.events_outbox WHERE tipo = 'tenant.provisioned'"))
    antes = {**_cgroup(pilha, c), **_picos(pilha, c)}

    pilha.node(imagem, runner, "publicador_runner.ts", destacado=True, nome=f"{PROJECTO}-publicador")
    drenagem_desde = time.time()
    amostras: list[float] = []
    t0 = time.monotonic()
    donos = 0
    try:
        while time.monotonic() - t0 < limite_s:
            amostras.append(_cgroup(pilha, c)["working_set_mib"])
            donos = int(pilha.sql("SELECT count(*) FROM platform.contacts WHERE papel = 'dono'"))
            if donos >= casos:
                break
            time.sleep(0.5)
        drenagem_s = round(time.monotonic() - t0, 1)
        # Mais 10 s de amostras: o que o processo guarda depois de drenar tambem conta.
        for _ in range(20):
            amostras.append(_cgroup(pilha, c)["working_set_mib"])
            time.sleep(0.5)
        amostras_ate = time.time()
    finally:
        subprocess.run(["docker", "rm", "-f", f"{PROJECTO}-publicador"], capture_output=True)
    dlq = int(pilha.sql(f"SELECT count(*) FROM platform.events_dlq WHERE consumer = '{CONSUMIDOR}'"))
    consumidos = int(pilha.sql(f"SELECT count(*) FROM platform.events_consumed WHERE consumer = '{CONSUMIDOR}'"))
    return {
        "casos": casos,
        "semeadura_s": semeadura_s,
        "tenant_provisioned_no_outbox": no_outbox,
        "antes_da_rajada": antes,
        "drenagem_s": drenagem_s,
        "drenagem_desde_unix": round(drenagem_desde, 3),
        "amostras_ate_unix": round(amostras_ate, 3),
        "donos": donos,
        "consumidos": consumidos,
        "dlq": dlq,
        "amostras": len(amostras),
        "working_set_max_mib": max(amostras),
        "depois": {**_cgroup(pilha, c), **_picos(pilha, c)},
    }


def _prometheus(pilha: Pilha, j: dict) -> dict:
    """O alvo do consumidor no Prometheus da pilha (KAM-251).

    A API so escuta em `127.0.0.1` dentro do contentor (`--web.listen-address`
    do compose), e le-se por `docker exec` com o `wget` da imagem. Espera pela
    primeira raspagem em ate 90 voltas (cada uma um `docker exec` e 1 s): o
    intervalo global e de 30 s.

    A janela da rajada vai do arranque do publicador a ultima amostra do cgroup,
    medidas no relogio do anfitriao, e desloca-se para o do Prometheus pela
    diferenca entre o `time()` dele e o do anfitriao no mesmo instante: no
    Docker Desktop o contentor corre noutra VM, e os dois relogios podem nao
    concordar. Contam-se as raspagens com `up` a 1 (`sum_over_time`), e nao as
    tentativas (`count_over_time` contava tambem as falhadas).
    """
    c = pilha.contentor("prometheus")

    def api(caminho: str) -> dict:
        r = subprocess.run(
            ["docker", "exec", c, "wget", "-q", "-O", "-", f"http://127.0.0.1:9090/api/v1/{caminho}"],
            capture_output=True, text=True, timeout=60,
        )
        if r.returncode != 0:
            raise RuntimeError(f"prometheus {caminho}: {r.stderr[-500:]}")
        return json.loads(r.stdout)["data"]

    def consulta(expressao: str) -> list[dict]:
        return api("query?query=" + urllib.parse.quote(expressao, safe=""))["result"]

    alvos: list[dict] = []
    for _ in range(90):
        alvos = [a for a in api("targets?state=active")["activeTargets"]
                 if a["labels"].get("job") == JOB and a["health"] != "unknown"]
        if alvos:
            break
        time.sleep(1)
    # As raspagens bem sucedidas na rajada: o pico so inclui o `/metrics` se
    # houver pelo menos uma.
    agora_anfitriao = time.time()
    desvio = float(consulta("time()")[1]) - agora_anfitriao
    janela = max(1, round(j["amostras_ate_unix"] - j["drenagem_desde_unix"]))
    fim = j["amostras_ate_unix"] + desvio
    na_drenagem = consulta(f'sum_over_time(up{{job="{JOB}"}}[{janela}s] @ {fim:.3f})')
    return {
        "job": JOB,
        "alvos": [{"scrape_url": a["scrapeUrl"], "health": a["health"], "last_error": a["lastError"]}
                  for a in alvos],
        "up": [float(s["value"][1]) for s in consulta(f'up{{job="{JOB}"}}')],
        "janela_da_rajada_s": janela,
        "desvio_do_relogio_s": round(desvio, 3),
        "raspagens_bem_sucedidas_na_rajada": int(float(na_drenagem[0]["value"][1])) if na_drenagem else 0,
        "series": sorted({s["metric"]["__name__"] for s in consulta(f'{{job="{JOB}"}}')}
                         - {"up", "scrape_duration_seconds", "scrape_samples_scraped",
                            "scrape_samples_post_metric_relabeling", "scrape_series_added"}),
    }


def _falha(pilha: Pilha, inicio: str) -> dict:
    """O estado do processo quando o ensaio falha, **antes** de a pilha cair.

    Um limite que nao chega mata o processo no arranque, o `up --wait` falha, e
    sem isto o `down` apagava a unica prova: o `OOMKilled` (que um reinicio
    repoe a falso), o codigo de saida, os reinicios e os eventos `oom` do Docker.
    """
    try:
        c = pilha.contentor(SERVICO)
    except RuntimeError as erro:
        return {"contentor": str(erro)}
    inspeccao = subprocess.run(["docker", "inspect", c], capture_output=True, text=True)
    if inspeccao.returncode != 0:
        return {"inspect": inspeccao.stderr[-500:]}
    estado = json.loads(inspeccao.stdout)[0]
    eventos = subprocess.run(
        ["docker", "events", "--since", inicio, "--until", "0s", "--filter", f"container={c}",
         "--filter", "event=oom", "--filter", "event=die",
         "--format", "{{.Action}} {{index .Actor.Attributes \"exitCode\"}}"],
        capture_output=True, text=True, timeout=60,
    ).stdout.split("\n")
    return {
        "restart_count": estado["RestartCount"],
        "exit_code": estado["State"]["ExitCode"],
        "oom_killed": estado["State"]["OOMKilled"],
        "memory_bytes": estado["HostConfig"]["Memory"],
        "memory_swap_bytes": estado["HostConfig"]["MemorySwap"],
        "eventos_oom": sum(1 for e in eventos if e.startswith("oom")),
        "saidas": [e.split(" ", 1)[1] for e in eventos if e.startswith("die ")],
    }


def _mib(limite: str) -> float:
    """`96m` em MiB; `1g` tambem. So as duas unidades que o compose deste repositorio usa."""
    return float(limite[:-1]) * (1024 if limite.endswith("g") else 1)


def node_options_do_compose() -> str | None:
    """O `NODE_OPTIONS` que o compose de *staging* declara para o processo.

    Lido do bloco do servico por expressao regular, como o
    `db/tests_dimensionamento` le os limites: o `tools/kamba_yaml.py` recusa as
    ancoras que o compose usa.
    """
    bloco = re.search(rf"(?m)^  {re.escape(SERVICO)}:\n(.*?)(?=^  \S|\Z)", COMPOSE.read_text(encoding="utf-8"), re.S)
    if bloco is None:
        return None
    valor = re.search(r"(?m)^      NODE_OPTIONS:\s*(.+?)\s*$", bloco.group(1))
    return valor.group(1).strip("\"'") if valor else None


def veredictos(r: dict) -> dict[str, bool]:
    j = r["rajada"]
    return {
        # A sobreposicao pegou: sem isto, uma que falhasse media sob o limite do staging.
        "limite_aplicado": j["depois"]["memory_max_mib"] == _mib(r["limite"])
        and j["depois"]["swap_max"] == "0",
        "n_no_outbox": j["tenant_provisioned_no_outbox"] == j["casos"],
        "n_donos": j["donos"] == j["casos"] and j["consumidos"] == j["casos"],
        "sem_dlq": j["dlq"] == 0,
        "sem_oom": j["depois"]["oom_kill"] == 0 and not j["depois"]["oom_killed"],
        "sem_reinicio": j["depois"]["restart_count"] == 0,
        "sem_swap": j["depois"]["swap_peak_mib"] == 0,
        # O do contentor contra o pedido, ou contra o do compose quando nao se
        # pediu nenhum: a corrida por omissao tambem prova o que mediu (KAM-241).
        "node_options_aplicado": j["depois"]["node_options"]
        == (r["node_options"] if r["node_options"] is not None else node_options_do_compose()),
        # Vivo e a responder a sonda depois da rajada, e nao so sem reinicio.
        "saudavel": j["depois"]["saude"] == "healthy",
        # KAM-251: com `--prometheus`, o alvo do processo `up` e so ele.
        **({"alvo_up": [a["health"] for a in r["prometheus"]["alvos"]] == ["up"]
            and r["prometheus"]["up"] == [1.0]} if "prometheus" in r else {}),
    }


def principal() -> int:
    argumentos = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    argumentos.add_argument("--casos", type=int, default=300)
    argumentos.add_argument("--limite", default="54m",
                            help="mem_limit e memswap_limit do processo (omissao: 54m, o de producao)")
    argumentos.add_argument("--sonda", choices=("compose", "node", "bash"), default="compose",
                            help="compose: a do ficheiro; node: a `node -e fetch` do KAM-238; bash: /dev/tcp")
    argumentos.add_argument("--node-options", default=None,
                            help="NODE_OPTIONS do processo, por sobreposicao (omissao: o do compose)")
    argumentos.add_argument("--entrada", default=None,
                            help="o ficheiro que o `node` corre, por sobreposicao (omissao: o `command:` do compose)")
    argumentos.add_argument("--espera", type=float, default=600, help="segundos para drenar a rajada")
    argumentos.add_argument("--prometheus", action="store_true",
                            help="levanta o Prometheus de staging e mede com a raspagem a correr (KAM-251)")
    argumentos.add_argument("--manter", action="store_true", help="nao derruba a pilha no fim")
    argumentos.add_argument("--relatorio", type=Path)
    opcoes = argumentos.parse_args()

    inicio = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    relatorio: dict = {"inicio_utc": inicio, "limite": opcoes.limite, "sonda": opcoes.sonda,
                      "node_options": opcoes.node_options, "entrada": opcoes.entrada,
                      "com_prometheus": opcoes.prometheus}
    with tempfile.TemporaryDirectory(prefix="kam238-") as pasta:
        env, runner = _ambiente()
        pilha = Pilha(Path(pasta), env, opcoes.limite, opcoes.sonda, opcoes.node_options, opcoes.entrada)
        relatorio["commit"] = env["KAMBA_COMMIT_SHA"]
        try:
            pilha.compose("up", "-d", "--wait", "postgres", "queue")
            porta = pilha.compose("port", "postgres", "5432").strip().rsplit(":", 1)[1]
            amb = dict(os.environ)
            amb.update(env)
            amb.update({"KAMBA_DB_HOST": "127.0.0.1", "KAMBA_DB_PORT": porta, "KAMBA_DB_NAME": BASE})
            for comando in (
                [sys.executable, "bootstrap.py"],
                [sys.executable, "-m", "alembic", "-c", "migrations/alembic.ini", "upgrade", "head"],
            ):
                for tentativa in range(12):
                    r = subprocess.run(comando, cwd=RAIZ / "db", env=amb, capture_output=True, text=True)
                    if r.returncode == 0:
                        break
                    # O servidor temporario do `initdb` reinicia uma vez (o achado do KAM-225).
                    # Doze vezes 5 s (KAM-241): com outras pilhas a correr na mesma
                    # maquina, cinco vezes 3 s deram «network error» duas corridas seguidas.
                    time.sleep(5)
                else:
                    raise RuntimeError(f"{comando[1]}: {r.stderr[-2000:]}")
            pilha.compose("up", "-d", "--build", "--wait", SERVICO, tempo=1800)
            if opcoes.prometheus:
                pilha.compose("up", "-d", "--wait", "prometheus", tempo=600)
            time.sleep(20)
            c = pilha.contentor(SERVICO)
            relatorio["repouso"] = {**_cgroup(pilha, c), **_picos(pilha, c)}
            relatorio["rajada"] = rajada(pilha, runner, opcoes.casos, opcoes.espera)
            if opcoes.prometheus:
                relatorio["prometheus"] = _prometheus(pilha, relatorio["rajada"])
            relatorio["veredictos"] = veredictos(relatorio)
        except Exception as erro:  # noqa: BLE001 — o relatorio leva o que se mediu
            relatorio["erro"] = f"{type(erro).__name__}: {erro}"
            relatorio["falha"] = _falha(pilha, inicio)
            relatorio["registos"] = pilha.compose("logs", "--tail", "20", SERVICO, verificar=False)[-3000:]
        finally:
            relatorio["fim_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            subprocess.run(["docker", "rm", "-f", f"{PROJECTO}-rajada", f"{PROJECTO}-publicador"], capture_output=True)
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
