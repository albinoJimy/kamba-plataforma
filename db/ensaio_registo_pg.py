"""O ensaio do KAM-225: a recusa sobre o tecto, lida do registo, numa pilha levantada.

    python db/ensaio_registo_pg.py [--manter] [--relatorio caminho.json]

No molde do `db/ensaio_idx.py` (KAM-194), e reutilizando o ambiente do
`db/ensaio_consumidores.py`: levanta, do **compose de staging** e com o nome de
projecto `kam225-ensaio`, o PostgreSQL **com o `command:` do compose** (o
`jsonlog` num volume proprio), cria os papeis, aplica as migracoes — com os
privilegios do KAM-096 sobre `platform.trust_level` —, e levanta o recolector
`registo-pg` e o Prometheus com as regras do repositorio. Depois mede:

    a configuracao    o `SHOW` do servidor: o colector ligado e o `jsonlog`.
    o controlo        o `kamba_batch`, por uma ligacao directa, apaga uma linha
                      do tecto (a base recusa: `42501`, que o registo escreve) e
                      escreve-o (a base aceita, sem erro). O contador fica a zero
                      e a regra `confianca_tecto_recusado_no_registo` nao
                      dispara, com o Prometheus a ter raspado a serie.
    o adversarial     o `kamba_app` tenta mudar o tecto por duas ligacoes
                      directas que nao passam pelo `tenant_guard` — o `psql` dentro
                      do contentor e um processo Python (`pg8000`) de fora —, e le
                      o motivo. Tres `42501`; o contador passa a 3, e a regra
                      dispara (`ALERTS{alertstate="firing"}` no Prometheus).
    a memoria         o `docker stats` do `registo-pg` no fim.
    o registo         as linhas `42501` sem `statement` (`log_min_error_statement=panic`),
                      e a idade do `jsonlog` servida e abaixo de uma hora.

Os segredos sao gerados nesta execucao e nao se imprimem; os dados sao
sinteticos. O registo do servidor fica no volume da pilha, que o `down -v`
apaga; o relatorio leva so os tres campos de cada linha `42501`, nunca o
`statement`.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ensaio_consumidores import ADMIN, BASE, COMPOSE, RAIZ, _ambiente, _esperar  # noqa: E402

PROJECTO = "kam225-ensaio"
RECOLECTOR = "registo-pg"
SERVICOS = (RECOLECTOR, "prometheus")
METRICA = "registo_pg_tecto_recusado_total"
IDADE = "registo_pg_idade_do_registo_segundos"
ALERTA = "confianca_tecto_recusado_no_registo"
#: O `scrape_interval` e o `evaluation_interval` sao 30 s: duas voltas e folga.
ESPERA_DO_ALERTA_S = 150.0

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
        self.env = env
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

    def executar(self, contentor: str, *args: str, env: dict[str, str] | None = None,
                 verificar: bool = True) -> subprocess.CompletedProcess:
        extra = [a for k in (env or {}) for a in ("-e", k)]
        r = subprocess.run(["docker", "exec", *extra, contentor, *args], capture_output=True,
                           text=True, timeout=180, encoding="utf-8", errors="replace",
                           env={**os.environ, **(env or {})})
        if verificar and r.returncode != 0:
            raise RuntimeError(f"docker exec {args[:2]}: {r.stderr[-1000:]}")
        return r

    def sql(self, consulta: str) -> str:
        return self.executar(self.contentor("postgres"), "psql", "-U", ADMIN, "-d", BASE,
                             "-v", "ON_ERROR_STOP=1", "-At", "-c", consulta).stdout.strip()

    def psql_como(self, papel: str, consulta: str) -> str:
        """Uma ligacao **directa**, por TCP e com a palavra-passe do papel: nao e o `tenant_guard`."""
        senha = self.env[f"KAMBA_SECRET_DB_{papel.removeprefix('kamba_').upper()}_PASSWORD"]
        r = self.executar(self.contentor("postgres"), "psql", "-h", "127.0.0.1", "-U", papel,
                          "-d", BASE, "-At", "-c", consulta, env={"PGPASSWORD": senha},
                          verificar=False)
        return (r.stderr or r.stdout).strip()

    def serie(self, nome: str) -> float:
        codigo = ("import urllib.request,sys;sys.stdout.write(urllib.request.urlopen("
                  "'http://127.0.0.1:8225/metrics').read().decode())")
        texto = self.executar(self.contentor(RECOLECTOR), "python", "-c", codigo).stdout
        for linha in texto.splitlines():
            if linha.startswith(f"{nome} "):
                return float(linha.split()[1])
        raise RuntimeError(f"{nome} nao esta no /metrics")

    def contador(self) -> float:
        return self.serie(METRICA)

    def prometheus(self, consulta: str) -> list[dict]:
        url = "http://127.0.0.1:9090/api/v1/query?query=" + urllib.parse.quote(consulta)
        texto = self.executar(self.contentor("prometheus"), "wget", "-q", "-O", "-", url).stdout
        return json.loads(texto)["data"]["result"]

    def linhas_42501(self) -> list[dict]:
        """Os tres campos de cada linha `42501` do registo — nunca o `statement`."""
        r = self.executar(self.contentor("postgres"), "sh", "-c",
                          'cat /var/log/postgresql/*.json | grep \'"state_code":"42501"\' || true')
        campos = []
        for linha in r.stdout.splitlines():
            registo = json.loads(linha)
            campos.append({k: registo.get(k) for k in ("user", "state_code", "message")})
            # O `statement` nao vem (`log_min_error_statement=panic`); se viesse,
            # diz-se que veio, e o texto nao sai daqui.
            campos[-1]["traz_statement"] = "statement" in registo
        return campos


def _alerta(pilha: Pilha) -> list[dict]:
    return pilha.prometheus(f'ALERTS{{alertname="{ALERTA}",alertstate="firing"}}')


def configuracao(pilha: Pilha) -> dict:
    return {
        nome: pilha.sql(f"SHOW {nome}")
        for nome in ("logging_collector", "log_destination", "log_directory", "log_filename",
                     "log_truncate_on_rotation", "log_file_mode")
    }


def controlo(pilha: Pilha) -> dict:
    """O `kamba_batch`: uma recusa dele (apagar) e uma escrita aceite. Nada conta, nada dispara."""
    # A serie tem de estar no Prometheus **antes**: sem amostra a zero, o
    # controlo nao provava nada sobre o `increase`.
    _esperar(lambda: pilha.prometheus(METRICA), 120, passo=5)
    apagar = pilha.psql_como("kamba_batch", "DELETE FROM platform.trust_level")
    escrever = pilha.psql_como(
        "kamba_batch", "UPDATE platform.trust_level SET tecto_pedido_minor = tecto_pedido_minor")
    time.sleep(70)  # duas voltas de raspagem e de avaliacao
    return {
        "apagar_como_kamba_batch": apagar,
        "escrever_como_kamba_batch": escrever,
        "linhas_42501_no_registo": pilha.linhas_42501(),
        "contador": pilha.contador(),
        "serie_no_prometheus": [r["value"][1] for r in pilha.prometheus(METRICA)],
        "alerta_a_disparar": _alerta(pilha),
    }


def adversarial(pilha: Pilha, porta: str) -> dict:
    """O `kamba_app`, por duas ligacoes directas: `psql` e um processo Python."""
    resultado = {
        "update_psql": pilha.psql_como(
            "kamba_app", "UPDATE platform.trust_level SET tecto_pedido_minor = 999999999"),
        "select_motivo_psql": pilha.psql_como("kamba_app", "SELECT motivo FROM platform.trust_level"),
    }
    import pg8000.dbapi

    ligacao = pg8000.dbapi.connect(user="kamba_app", password=pilha.env["KAMBA_SECRET_DB_APP_PASSWORD"],
                                   host="127.0.0.1", port=int(porta), database=BASE,
                                   application_name="ensaio-kam225")
    try:
        cursor = ligacao.cursor()
        try:
            cursor.execute("UPDATE platform.trust_level SET tecto_pedido_minor = 999999999")
            resultado["update_python"] = "aceite"
        except pg8000.dbapi.DatabaseError as erro:
            detalhe = erro.args[0] if erro.args and isinstance(erro.args[0], dict) else {}
            resultado["update_python"] = f"{detalhe.get('C')} {detalhe.get('M')}"
    finally:
        ligacao.close()
    resultado["contador_em_s"] = _esperar(lambda: pilha.contador() >= 3, 30, passo=0.5)
    resultado["contador"] = pilha.contador()
    inicio = time.monotonic()
    disparou = _esperar(lambda: _alerta(pilha), ESPERA_DO_ALERTA_S, passo=5)
    resultado["alerta_em_s"] = round(time.monotonic() - inicio, 1) if disparou else None
    resultado["alerta_a_disparar"] = [r["metric"] for r in _alerta(pilha)]
    resultado["linhas_42501_no_registo"] = pilha.linhas_42501()
    resultado["idade_do_registo_s"] = pilha.serie(IDADE)
    return resultado


def memoria(pilha: Pilha) -> str:
    return subprocess.run(
        ["docker", "stats", "--no-stream", "--format", "{{.MemUsage}}", pilha.contentor(RECOLECTOR)],
        capture_output=True, text=True, timeout=60,
    ).stdout.strip()


def veredictos(r: dict) -> dict[str, bool]:
    cfg, ctl, adv = r["configuracao"], r["controlo"], r["adversarial"]
    papeis_ctl = [l["user"] for l in ctl["linhas_42501_no_registo"]]
    return {
        "jsonlog ligado": cfg["logging_collector"] == "on" and cfg["log_destination"] == "jsonlog",
        "controlo: o kamba_batch e recusado ao apagar (42501 no registo)": papeis_ctl == ["kamba_batch"],
        "controlo: a escrita do kamba_batch passa": ctl["escrever_como_kamba_batch"].startswith("UPDATE"),
        "controlo: o contador fica a zero": ctl["contador"] == 0,
        "controlo: o Prometheus raspou a serie a zero": ctl["serie_no_prometheus"] == ["0"],
        "controlo: o alerta nao dispara": ctl["alerta_a_disparar"] == [],
        "adversarial: tres 42501 por ligacao directa": all(
            "permission denied for table trust_level" in adv[k]
            for k in ("update_psql", "select_motivo_psql", "update_python")
        ),
        "adversarial: o contador passa a 3": adv["contador"] == 3,
        "adversarial: o alerta dispara": bool(adv["alerta_a_disparar"]),
        "o registo nao traz o statement": not any(
            l["traz_statement"] for l in adv["linhas_42501_no_registo"]
        ),
        "a idade do registo e servida e esta abaixo de uma hora": 0 <= adv["idade_do_registo_s"] < 3600,
    }


def principal() -> int:
    argumentos = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    argumentos.add_argument("--manter", action="store_true", help="nao derruba a pilha no fim")
    argumentos.add_argument("--relatorio", type=Path)
    opcoes = argumentos.parse_args()

    relatorio: dict = {"inicio_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    with tempfile.TemporaryDirectory(prefix="kam225-") as pasta:
        env = _ambiente()
        env["KAMBA_DB_NAME"] = BASE
        pilha = Pilha(Path(pasta), env)
        relatorio["commit"] = env["KAMBA_COMMIT_SHA"]
        try:
            pilha.compose("up", "-d", "--wait", "postgres")
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
                # O `--wait` da o servidor por saudavel ainda durante o servidor
                # temporario do `initdb`, que depois reinicia: numa maquina
                # carregada a primeira ligacao apanha o reinicio (medido, a
                # terceira corrida deste ensaio). Repete-se so o erro de rede.
                for tentativa in range(6):
                    r = subprocess.run(comando, cwd=RAIZ / "db", env=amb, capture_output=True, text=True)
                    if r.returncode == 0 or "network error" not in r.stderr or tentativa == 5:
                        break
                    time.sleep(5)
                if r.returncode != 0:
                    raise RuntimeError(f"{comando[1]}: {r.stderr[-2000:]}")
            relatorio["configuracao"] = configuracao(pilha)
            pilha.compose("up", "-d", "--build", "--wait", "--no-deps", *SERVICOS, tempo=1800)
            relatorio["estado"] = pilha.compose("ps", "--format", "{{.Service}} {{.Status}}")
            relatorio["controlo"] = controlo(pilha)
            relatorio["adversarial"] = adversarial(pilha, porta)
            relatorio["memoria_do_recolector"] = memoria(pilha)
            relatorio["veredictos"] = veredictos(relatorio)
        except Exception as erro:  # noqa: BLE001 — o relatorio leva o que se mediu
            relatorio["erro"] = f"{type(erro).__name__}: {erro}"
            relatorio["registos"] = {
                s: pilha.compose("logs", "--tail", "20", s, verificar=False)[-3000:]
                for s in ("postgres", *SERVICOS)
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
