"""O ensaio local do simulacro, em Docker: cenarios A, B e C (KAM-085).

    cd tools
    python -m dr_simulacro ensaio preparar --saida D --gib 20   # base, backup, export
    python -m dr_simulacro ensaio a --saida D                   # perda do host
    python -m dr_simulacro ensaio c --saida D                   # cofre indisponivel
    python -m dr_simulacro ensaio preparar-b --saida D          # corrupcao logica
    python -m dr_simulacro ensaio b1|b2 --saida D               # PITR, a letra e com exportacao
    python -m dr_simulacro ensaio pid1 --saida D                # o controlo do PID 1
    python -m dr_simulacro ensaio limpar --saida D

## O que corre, e o que e emulado

Corre **a serio**: o PostgreSQL 18.6 da imagem do compose (fixada pelo mesmo
*digest*), o pgBackRest do PGDG, a configuracao de `infra/backup/` **montada
tal como esta em git** (`pgbackrest.conf` como ficheiro; o
`postgres-arquivo.conf` traduzido linha a linha para `-c`, porque o *entrypoint*
da imagem nao tem `include`), o esquema real (`db/bootstrap.py` e `alembic
upgrade head`), a cadeia do `audit_log` escrita pelo *trigger* real e
verificada pelo `db/auditoria.py` real, e as tabelas reais do *outbox*.

E **emulado**, e cada resultado o diz:

- o `repo1` e um **volume Docker** e nao um *host* noutro dominio de falha: o
  repositorio sobrevive a morte do primario porque e outro volume, nao porque
  esta noutro sitio. O debito medido e de **disco e CPU**, nao de rede;
- o «novo *host* por IaC» e um contentor novo no mesmo motor, com volume novo.
  Mede-se, e **nao** substitui os 30 min do §8.2, que sao do KAM-075 e da D1;
- a deteccao, a decisao e o DNS sao humanos ou nao existem: a folha
  escreve-os `nao_medido`, com a razao.

## Os segredos do ensaio

Sao **sinteticos e desta execucao**: a palavra-passe do administrador, as oito
dos papeis, a passphrase do repositorio e a passphrase da exportacao offline.
Geram-se no `preparar` e ficam em `<saida>/segredos.json`, **fora do
repositorio**, porque o repositorio cifrado do `preparar` so se le com a
mesma passphrase nos cenarios seguintes. O `limpar` apaga o ficheiro. Passam
aos contentores pelo ambiente (`-e NOME`, sem valor na linha de comandos).
"""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from . import calculo, folha, imagem_condutor, marcadores

PREFIXO = "kam085"
REDE = f"{PREFIXO}-dr"
IMAGEM_PG_BASE = (
    "pgvector/pgvector:0.8.7-pg18"
    "@sha256:2358fcba361ed2233a5ed81b5fe4ca779ccb304120ce531a3bf51c0ed7e2bc11"
)
IMAGEM_PY_BASE = imagem_condutor.IMAGEM
IMAGEM_PG = f"{PREFIXO}-pg:local"
IMAGEM_CONDUTOR = f"{PREFIXO}-condutor:local"
PGDATA = "/var/lib/postgresql/18/docker"
REPO_NO_CONTENTOR = "/var/lib/pgbackrest"
ADMIN = "kamba"
BASE = "kamba_platform"
BASE_DA_CARGA = "kamba_simulacro_carga"
#: As bases nao se nomeiam: contam-se **todas** as que o cluster tem, lidas do
#: `pg_database`. E a cobertura certa para um restauro — o pgBackRest restaura o
#: cluster inteiro —, e e tambem o que mantem este ficheiro fora da regra do
#: KAM-042 (`tools/lint_arch/medusa.py`): nenhum componente fora do COM nomeia a
#: base do Registo. O ensaio le-a como administrador do cluster, como o proprio
#: backup, e nao como componente; quem quiser uma excepcao a regra pede-a ao
#: fundador, que e quem decide criterios de *gate*.
SQL_BASES = "SELECT datname FROM pg_database WHERE NOT datistemplate ORDER BY 1;"
#: Uma linha de carga: dois `gen_random_bytes` (o maximo de cada um e 1024), que
#: ficam abaixo do limiar do TOAST e por isso **nao** se comprimem na base.
#: Aleatorios de proposito: e o pior caso para o repositorio (`zst` nao os
#: reduz) e para a rede, e uma base real comprime melhor do que isto.
BYTES_POR_LINHA = 1824
LINHAS_POR_LOTE = 400_000

DOCKERFILE_PG = f"""\
FROM {IMAGEM_PG_BASE}
RUN apt-get update -qq \\
 && apt-get install -y -qq --no-install-recommends pgbackrest gnupg >/dev/null \\
 && rm -rf /var/lib/apt/lists/* \\
 && install -d -o postgres -g postgres -m 0750 /var/spool/pgbackrest \\
      /var/log/pgbackrest {REPO_NO_CONTENTOR} /etc/pgbackrest
"""

DOCKERFILE_CONDUTOR = f"""\
FROM {IMAGEM_PY_BASE}
COPY migrations.txt /tmp/migrations.txt
RUN pip install --quiet --no-cache-dir --timeout 120 --retries 10 --require-hashes --no-deps -r /tmp/migrations.txt
"""

VARIAVEIS_DOS_PAPEIS = (
    "KAMBA_SECRET_DB_MIGRATOR_PASSWORD", "KAMBA_SECRET_DB_APP_PASSWORD",
    "KAMBA_SECRET_DB_BATCH_PASSWORD", "KAMBA_SECRET_DB_RESOLVER_PASSWORD",
    "KAMBA_SECRET_DB_IDENTITY_PASSWORD", "KAMBA_SECRET_DB_AUDIT_PASSWORD",
    "KAMBA_SECRET_DB_AGR_PASSWORD", "KAMBA_SECRET_DB_PAY_HOOKS_PASSWORD",
)

#: O nome da passphrase do repositorio no cofre, pelo `ops/secrets-inventory.yaml`
#: (`backup_repo_cifra_passphrase`) e pela regra `KAMBA_SECRET_<ID>` do ADR-L002.
NOME_NO_COFRE = "KAMBA_SECRET_BACKUP_REPO_CIFRA_PASSPHRASE"

#: Ler a exportacao decifrada **sem** Python nem `jq` no host de restauro: a
#: imagem da base so tem `sh`, `grep` e `sed`, e o JSON do `json.dumps` e uma
#: linha so. Contar e extrair com o que ha e o que o operador vai ter.
CONTAR_SEGREDOS = "grep -o '\"KAMBA_SECRET_[A-Z_]*\"' /dev/shm/cofre.json | wc -l"
EXTRAIR_PASSPHRASE = (
    f"sed -n 's/.*\"{NOME_NO_COFRE}\": \"\\([^\"]*\\)\".*/\\1/p' /dev/shm/cofre.json"
)


class EnsaioFalhou(RuntimeError):
    """Um passo do ensaio nao fez o que devia. A mensagem diz qual."""


def agora() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# O que se le dos ficheiros de `infra/backup/`, e se testa sem Docker
# ---------------------------------------------------------------------------


def opcoes_do_arquivo(texto: str, sem: tuple[str, ...] = ()) -> list[str]:
    """O `postgres-arquivo.conf` em pares `-c chave=valor`, pela ordem do ficheiro.

    A imagem arranca o `postgres` sem `include`, e montar o fragmento como
    `postgresql.conf` substituia o ficheiro inteiro. Traduzir linha a linha
    mantem o ficheiro de git como fonte: um `archive_timeout` mudado la muda o
    ensaio, que e o que se quer de um ensaio da configuracao.

    As aspas simples de um valor saem, porque o `-c` nao passa por shell.
    `sem` tira chaves — o `preparar` gera a carga com o arquivo desligado.
    """
    opcoes = []
    for linha in texto.splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, valor = (parte.strip() for parte in linha.split("=", 1))
        if chave in sem:
            continue
        if len(valor) >= 2 and valor[0] == valor[-1] == "'":
            valor = valor[1:-1]
        opcoes += ["-c", f"{chave}={valor}"]
    return opcoes


def cpu_em_pct(texto: str) -> float:
    """`12.5%` do `docker stats` em 12.5; um traco (contentor a arrancar) e zero."""
    try:
        return float(texto.strip().rstrip("%"))
    except ValueError:
        return 0.0


def tamanho_em_bytes(texto: str) -> int:
    """A primeira palavra de um `du -sb`."""
    return int(texto.split()[0])


# ---------------------------------------------------------------------------
# O executor
# ---------------------------------------------------------------------------


class Docker:
    """`docker <args>` com o ambiente dos segredos, e falha alta por omissao."""

    def __init__(self, ambiente: dict[str, str], correr=subprocess.run):
        self.ambiente = ambiente
        self._correr = correr

    def __call__(self, *argumentos: str, entrada: str | None = None,
                 verificar: bool = True, tempo: float | None = None):
        resultado = self._correr(
            ["docker", *argumentos], input=entrada, capture_output=True, text=True,
            env=self.ambiente, timeout=tempo, encoding="utf-8", errors="replace",
        )
        if verificar and resultado.returncode != 0:
            raise EnsaioFalhou(
                f"docker {' '.join(argumentos[:3])} ... saiu com {resultado.returncode}: "
                f"{(resultado.stderr or resultado.stdout).strip()[-800:]}"
            )
        return resultado


# ---------------------------------------------------------------------------
# O ensaio
# ---------------------------------------------------------------------------


class Ensaio:
    def __init__(self, raiz: Path, saida: Path, docker: Docker | None = None,
                 dormir=time.sleep):
        self.raiz = raiz
        self.saida = saida
        self.saida.mkdir(parents=True, exist_ok=True)
        self.segredos = self._segredos()
        ambiente = dict(os.environ)
        ambiente.update(self.segredos)
        self.docker = docker or Docker(ambiente)
        self._dormir = dormir

    # --- segredos e registo ------------------------------------------------

    def _segredos(self) -> dict[str, str]:
        caminho = self.saida / "segredos.json"
        if caminho.exists():
            return json.loads(caminho.read_text(encoding="utf-8"))
        valores = {nome: secrets.token_urlsafe(24) for nome in VARIAVEIS_DOS_PAPEIS}
        valores["POSTGRES_PASSWORD"] = secrets.token_urlsafe(24)
        valores["KAM085_PG_SENHA"] = valores["POSTGRES_PASSWORD"]
        valores["PGBACKREST_REPO1_CIPHER_PASS"] = secrets.token_urlsafe(32)
        valores["KAM085_OFFLINE_PASSPHRASE"] = secrets.token_urlsafe(32)
        caminho.write_text(json.dumps(valores), encoding="utf-8")
        return valores

    def registar(self, nome: str, carga: dict) -> None:
        caminho = self.saida / f"{nome}.json"
        caminho.write_text(json.dumps(carga, indent=2, ensure_ascii=False, default=str),
                           encoding="utf-8")

    def contencao(self) -> list[dict]:
        """Os contentores que **nao** sao deste ensaio, com o CPU de agora.

        Uma cronometragem com outro ensaio a correr no mesmo motor nao mede o
        RTO; mede a disputa. Regista-se antes e depois de cada passo medido,
        e o relatorio declara a medicao contaminada se aparecer carga alheia.
        """
        saida = self.docker("stats", "--no-stream", "--format",
                            "{{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}").stdout
        outros = []
        for linha in saida.splitlines():
            partes = linha.split("\t")
            if len(partes) == 3 and not partes[0].startswith(PREFIXO):
                outros.append({"nome": partes[0], "cpu": partes[1], "memoria": partes[2]})
        return outros

    def esperar_sossego(self, limite_pct: float = 10.0, ate_segundos: float = 3600,
                        seguidas: int = 3) -> dict:
        """Espera ate a carga alheia somar menos de `limite_pct` de CPU, `seguidas` vezes.

        A maquina e partilhada com outros ensaios. Nao se mata o trabalho de
        ninguem: espera-se, e se o sossego nao chegar devolve-se `sossegado:
        false`, que o relatorio le como medicao contaminada.
        """
        fim = time.monotonic() + ate_segundos
        boas = 0
        amostras = []
        while time.monotonic() < fim:
            outros = self.contencao()
            soma = sum(cpu_em_pct(o["cpu"]) for o in outros)
            amostras.append(round(soma, 1))
            boas = boas + 1 if soma < limite_pct else 0
            if boas >= seguidas:
                return {"sossegado": True, "amostras": amostras[-10:]}
            self._dormir(10)
        return {"sossegado": False, "amostras": amostras[-10:]}

    # --- imagens, rede, volumes -------------------------------------------

    def imagens(self) -> None:
        self.docker("build", "-q", "-t", IMAGEM_PG, "-", entrada=DOCKERFILE_PG, tempo=1800)
        self.docker("build", "-q", "-t", IMAGEM_CONDUTOR, "-f", "-",
                    str(self.raiz / "db" / "requirements"),
                    entrada=DOCKERFILE_CONDUTOR, tempo=1800)

    def rede(self) -> None:
        if self.docker("network", "inspect", REDE, verificar=False).returncode != 0:
            self.docker("network", "create", REDE)

    # --- hosts -------------------------------------------------------------

    def _montagens_da_configuracao(self) -> list[str]:
        backup = self.raiz / "infra" / "backup"
        initdb = self.raiz / "infra" / "compose" / "postgres" / "initdb"
        return [
            "-v", f"{backup / 'pgbackrest.conf'}:/etc/pgbackrest/pgbackrest.conf:ro",
            "-v", f"{initdb}:/docker-entrypoint-initdb.d:ro",
        ]

    def _ambiente_do_host(self, com_cifra: bool) -> list[str]:
        variaveis = ["-e", "POSTGRES_PASSWORD",
                     "-e", f"POSTGRES_USER={ADMIN}", "-e", f"POSTGRES_DB={BASE}",
                     "-e", f"PGBACKREST_REPO1_PATH={REPO_NO_CONTENTOR}",
                     "-e", f"PGBACKREST_PG1_PATH={PGDATA}",
                     "-e", f"PGBACKREST_PG1_USER={ADMIN}",
                     "-e", f"PGBACKREST_PG1_DATABASE={BASE}"]
        if com_cifra:
            variaveis += ["-e", "PGBACKREST_REPO1_CIPHER_PASS"]
        return variaveis

    def opcoes_do_postgres(self, sem: tuple[str, ...] = ()) -> list[str]:
        texto = (self.raiz / "infra" / "backup" / "postgres-arquivo.conf").read_text(encoding="utf-8")
        return opcoes_do_arquivo(texto, sem=sem)

    def primario(self, nome: str, repo: str, geracao: bool = False,
                 init: bool = True, esperar: bool = True) -> None:
        """Um primario novo: o *entrypoint* da imagem faz o `initdb` e corre o `initdb/01`.

        **Com `--init` por omissao, e a razao e um achado deste ensaio** (fase
        `pid1`): sem ele o `postgres` e o PID 1 do contentor, o processo
        assincrono do `archive-push` (`archive-async=y` no `pgbackrest.conf`)
        fica orfao e e adoptado pelo *postmaster*, e quando sai com codigo
        diferente de zero o *postmaster* le-o como um filho seu que caiu e
        reinicia o cluster inteiro. Nenhum compose deste repositorio tem `init`.

        `geracao` arranca **sem** arquivo e com `wal_level=minimal`, so para
        escrever a carga sintetica: e anterior ao backup base, nao se mede, e
        com o WAL completo a escrita de 20 GiB era limitada pelo `WALWrite`
        (medido: ~4 MB/s neste disco). O primario e depois recriado sobre o
        mesmo volume com a configuracao de git (`reabrir_com_arquivo`).
        """
        self.docker("volume", "create", f"{nome}-dados")
        self.docker(
            "run", "-d", "--name", nome, "--hostname", nome, "--network", REDE,
            "--shm-size", "512m", *(["--init"] if init else []),
            *self._ambiente_do_host(com_cifra=True), *self._montagens_da_configuracao(),
            "-v", f"{nome}-dados:/var/lib/postgresql", "-v", f"{repo}:{REPO_NO_CONTENTOR}",
            IMAGEM_PG, "postgres",
            *self.opcoes_do_postgres(sem=("archive_mode",) if geracao else ()),
            *(["-c", "wal_level=minimal", "-c", "max_wal_senders=0"] if geracao else []),
            "-c", "max_wal_size=4GB", "-c", "shared_buffers=512MB",
        )
        if esperar:
            self.esperar(nome)

    def host_vazio(self, nome: str, repo: str, com_cifra: bool, repo_so_leitura: bool,
                   offline: Path | None = None) -> None:
        """O «novo host»: um contentor com volume novo e **sem** servidor a correr.

        O repositorio monta-se **so de leitura** no restauro: e a forma local da
        regra do §8.3 («restauro ... sem acesso de escrita»), e se o pgBackRest
        precisasse de escrever no repositorio para restaurar, isto falhava alto.
        """
        self.docker("volume", "create", f"{nome}-dados")
        modo = ":ro" if repo_so_leitura else ""
        extra = ["-v", f"{offline}:/offline:ro"] if offline else []
        self.docker(
            "run", "-d", "--name", nome, "--hostname", nome, "--network", REDE,
            "--shm-size", "512m", "--init",
            *self._ambiente_do_host(com_cifra=com_cifra), *self._montagens_da_configuracao(),
            "-v", f"{nome}-dados:/var/lib/postgresql", "-v", f"{repo}:{REPO_NO_CONTENTOR}{modo}",
            *extra, "--entrypoint", "sleep", IMAGEM_PG, "infinity",
        )
        self.docker("exec", nome, "install", "-d", "-o", "postgres", "-g", "postgres",
                    "-m", "0700", PGDATA)

    def esperar(self, nome: str, limite: float = 600) -> None:
        """Ate uma consulta real responder duas vezes seguidas (o *initdb* reinicia)."""
        fim = time.monotonic() + limite
        estaveis = 0
        while time.monotonic() < fim:
            r = self.docker("exec", nome, "psql", "-U", ADMIN, "-d", BASE, "-XAtqc",
                            "SELECT 1", verificar=False)
            estaveis = estaveis + 1 if r.returncode == 0 and r.stdout.strip() == "1" else 0
            if estaveis >= 2:
                return
            self._dormir(1)
        raise EnsaioFalhou(f"{nome}: a base nao respondeu em {limite:.0f} s")

    def matar(self, nome: str) -> None:
        """A perda do *host*: SIGKILL, e o disco vai com ele."""
        self.docker("kill", nome, verificar=False)
        self.docker("rm", "-f", nome, verificar=False)
        self.docker("volume", "rm", "-f", f"{nome}-dados", verificar=False)

    # --- SQL ---------------------------------------------------------------

    def psql(self, contentor: str, sql: str, base: str = BASE) -> str:
        return self.docker("exec", "-i", contentor, "psql", "-U", ADMIN, "-d", base,
                           "-X", "-q", "-A", "-t", "-v", "ON_ERROR_STOP=1", "-f", "-",
                           entrada=sql, tempo=7200).stdout

    def pgbackrest(self, contentor: str, *argumentos: str, ambiente: list[str] | None = None,
                   tempo: float = 7200) -> str:
        return self.docker("exec", "-u", "postgres", *(ambiente or []), contentor,
                           "pgbackrest", "--stanza=kamba", *argumentos, tempo=tempo).stdout

    def condutor(self, *comando: str, nome: str | None = None, destacado: bool = False,
                 host: str = "", tempo: float = 3600) -> str:
        """Um processo no contentor condutor, com `tools/` e `db/` montados so de leitura."""
        argumentos = ["run", "--network", REDE, "-e", "PYTHONPATH=/repo/tools",
                      "-e", "PYTHONDONTWRITEBYTECODE=1", "-e", "KAM085_PG_SENHA",
                      "-e", "POSTGRES_PASSWORD", "-e", f"POSTGRES_USER={ADMIN}",
                      "-e", f"KAMBA_DB_HOST={host}", "-e", "KAMBA_DB_PORT=5432",
                      "-e", f"KAMBA_DB_NAME={BASE}",
                      *[parte for v in VARIAVEIS_DOS_PAPEIS for parte in ("-e", v)],
                      "-v", f"{self.raiz / 'tools'}:/repo/tools:ro",
                      "-v", f"{self.raiz / 'db'}:/repo/db:ro",
                      "-v", f"{self.saida}:/out", "-w", "/repo/db"]
        if destacado:
            argumentos += ["-d", "--name", nome]
        else:
            argumentos += ["--rm"]
        return self.docker(*argumentos, IMAGEM_CONDUTOR, *comando, tempo=tempo).stdout

    def contagens(self, contentor: str) -> dict[str, int]:
        """`count(*)` de cada tabela de `platform` e `dr_simulacro`, e de cada base."""
        sql = """
SELECT n.nspname || '.' || c.relname,
       (xpath('/row/c/text()', query_to_xml(
          format('SELECT count(*) AS c FROM %I.%I', n.nspname, c.relname),
          false, true, '')))[1]::text
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE c.relkind IN ('r', 'p') AND n.nspname IN ('platform', 'dr_simulacro', 'public')
 ORDER BY 1;
"""
        resultado = {}
        for base in self.psql(contentor, SQL_BASES).split():
            for linha in self.psql(contentor, sql, base=base).splitlines():
                if "|" in linha:
                    tabela, n = linha.split("|", 1)
                    resultado[f"{base}:{tabela}"] = int(n or 0)
        return resultado

    def marcadores_restaurados(self, contentor: str) -> list:
        texto = self.psql(contentor, """
COPY (SELECT seq, to_char(escrito_em AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"')
        FROM dr_simulacro.marcador ORDER BY seq) TO STDOUT WITH CSV;
""")
        return marcadores.ler_csv(texto)

    def instante_da_base(self, contentor: str) -> datetime:
        texto = self.psql(contentor, "SELECT to_char(clock_timestamp() AT TIME ZONE 'UTC', "
                                     "'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"');")
        return folha.ler_instante(texto.strip())

    # --- o esquema e a carga ------------------------------------------------

    def esquema(self, host: str, tenant: str) -> None:
        """Os papeis, as migracoes reais, as tabelas do ensaio e um *tenant* sintetico."""
        self.condutor("python", "bootstrap.py", host=host)
        self.condutor("python", "-m", "alembic", "-c", "migrations/alembic.ini",
                      "upgrade", "head", host=host)
        self.psql(host, marcadores.SQL_TABELA + _sql_eventos() + f"""
INSERT INTO platform.tenants (id, tipo, nome, estado)
VALUES ('{tenant}', 'pme', 'Tenant sintetico do simulacro', 'ativo');
""")

    def auditar(self, host: str, tenant: str, quantas: int, accao_id: str) -> None:
        """Linhas de `audit_log` pela funcao real; o *trigger* encadeia-as."""
        self.psql(host, f"""
SELECT platform.audit_append('{tenant}'::uuid, 'system', 'dr-simulacro', 'batch.run',
       'dr_simulacro', '{accao_id}-' || g, NULL, sha256(convert_to('{accao_id}' || g, 'UTF8')))
  FROM generate_series(1, {quantas}) g;
SELECT platform.audit_append(NULL, 'system', 'dr-simulacro', 'batch.run',
       'dr_simulacro', '{accao_id}-plataforma', NULL, sha256(convert_to('{accao_id}', 'UTF8')));
""")

    def carga(self, host: str, bytes_alvo: int) -> dict:
        """A base sintetica, por lotes, ate `pg_database_size` somar `bytes_alvo`."""
        self.psql(host, f"CREATE DATABASE {BASE_DA_CARGA};")
        self.psql(host, """
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE UNLOGGED TABLE carga (id bigint NOT NULL, bloco bytea NOT NULL);
""", base=BASE_DA_CARGA)
        inicio = time.monotonic()
        proximo = 1
        while self.tamanho_das_bases(host) < bytes_alvo:
            self.psql(host, f"""
INSERT INTO carga SELECT g, gen_random_bytes(1024) || gen_random_bytes({BYTES_POR_LINHA - 1024})
  FROM generate_series({proximo}, {proximo + LINHAS_POR_LOTE - 1}) g;
""", base=BASE_DA_CARGA)
            proximo += LINHAS_POR_LOTE
        # Com `wal_level=minimal`, o `SET LOGGED` sincroniza o ficheiro em vez de
        # o escrever no WAL; a tabela fica *logged* como qualquer outra, e e
        # assim que o backup base e o restauro a veem.
        self.psql(host, "ALTER TABLE carga SET LOGGED;", base=BASE_DA_CARGA)
        # **E congela-se, antes do backup base.** Uma tabela acabada de carregar
        # nunca foi lida: a primeira leitura de cada pagina grava *hint bits* e
        # poda-a, e com `wal_level=replica` isso e WAL. Medido na primeira
        # preparacao de 20 GiB: o `count(*)` de antes da falha escreveu 70 GB
        # em disco em 16 min, e esse WAL ia ser arquivado e repetido no
        # restauro — o *replay* medido seria o de um artefacto da carga e nao
        # o de uma base em producao, cujas paginas estao lidas ha muito. O
        # `VACUUM (FREEZE)` deixa-as como as de uma tabela envelhecida.
        self.psql(host, "VACUUM (FREEZE, ANALYZE) carga;", base=BASE_DA_CARGA)
        self.psql(host, "CHECKPOINT;")
        return {"linhas": proximo - 1, "segundos": time.monotonic() - inicio,
                "bytes": self.tamanho_das_bases(host)}

    def tamanho_das_bases(self, host: str) -> int:
        texto = self.psql(host, "SELECT sum(pg_database_size(datname)) FROM pg_database;")
        return int(texto.strip())

    def reabrir_com_arquivo(self, host: str, repo: str) -> None:
        """O mesmo volume, o contentor de novo, agora com a configuracao de git inteira."""
        self.psql(host, "CHECKPOINT;")
        self.docker("stop", "-t", "120", host)
        self.docker("rm", host)
        self.primario(host, repo)

    def exportacao_do_cofre(self, host: str) -> dict:
        """A exportacao cifrada semanal do cofre, como o `ops/runbooks/secrets-export.md` §5.

        O cofre e sintetico: os segredos deste ensaio, com os nomes `KAMBA_SECRET_*`.
        Cifra-se com `gpg --symmetric --cipher-algo AES256`, a forma do runbook,
        com uma passphrase que **nao** esta no cofre (§4.3 do runbook).
        """
        offline = self.saida / "offline"
        offline.mkdir(exist_ok=True)
        cofre = {nome: valor for nome, valor in self.segredos.items()
                 if nome.startswith("KAMBA_SECRET_")}
        cofre[NOME_NO_COFRE] = self.segredos["PGBACKREST_REPO1_CIPHER_PASS"]
        carimbo = agora().strftime("%Y%m%dT%H%M%SZ")
        ficheiro = f"kamba-simulacro-{carimbo}.json.gpg"
        entrada = self.segredos["KAM085_OFFLINE_PASSPHRASE"] + "\n" + json.dumps(cofre)
        self.docker("exec", "-i", "-u", "postgres", host, "sh", "-c",
                    "read -r P; printf '%s' \"$P\" > /dev/shm/p; "
                    "gpg --batch --yes --quiet --pinentry-mode loopback --passphrase-file /dev/shm/p "
                    "--symmetric --cipher-algo AES256 --output /tmp/export.gpg; rm -f /dev/shm/p",
                    entrada=entrada)
        conteudo = self.docker("exec", host, "base64", "-w0", "/tmp/export.gpg").stdout
        import base64

        (offline / ficheiro).write_bytes(base64.b64decode(conteudo))
        self.docker("exec", host, "rm", "-f", "/tmp/export.gpg")
        return {"ficheiro": ficheiro, "segredos": len(cofre)}


def _sql_eventos() -> str:
    from .eventos import SQL_TABELAS

    return SQL_TABELAS


# ---------------------------------------------------------------------------
# Os passos, um por funcao, cada um cronometrado na folha
# ---------------------------------------------------------------------------

TENANT = "00000000-0000-4000-8000-000000000085"
REPO_A = f"{PREFIXO}-repo"
REPO_B = f"{PREFIXO}-repo-b"
PRIMARIO_A = f"{PREFIXO}-primario"
PRIMARIO_B = f"{PREFIXO}-primario-b"


def passo_iac(ensaio: Ensaio, f: folha.Folha, novo: str, repo: str, com_cifra: bool) -> dict:
    ensaio.matar(novo)  # um ensaio repetido parte de um host que nao existe
    contencao = {"antes": ensaio.contencao()}
    f.nao_medido("iac", "nao ha fornecedor nem modulo de IaC (KAM-075/D1); o host do ensaio "
                        "e um contentor, cronometrado a parte em iac_emulado e fora do RTO")
    f.inicio("iac_emulado", "contentor novo no mesmo motor e volume novo")
    ensaio.host_vazio(novo, repo, com_cifra=com_cifra, repo_so_leitura=True,
                      offline=ensaio.saida / "offline")
    f.fim("iac_emulado")
    return contencao


def passo_restauro(ensaio: Ensaio, f: folha.Folha, novo: str, comando: list[str],
                   nota: str, contencao: dict) -> int:
    f.inicio("restauro", nota)
    ensaio.docker("exec", "-u", "postgres", novo, *comando, tempo=14400)
    f.fim("restauro")
    contencao["depois_do_restauro"] = ensaio.contencao()
    return tamanho_em_bytes(ensaio.docker("exec", novo, "du", "-sb", PGDATA).stdout)


def passo_replay(ensaio: Ensaio, f: folha.Folha, novo: str) -> None:
    """Arranca o servidor restaurado e espera pelo fim da recuperacao.

    `pg_ctl -w` volta quando o servidor aceita ligacoes, o que com
    `hot_standby` acontece **durante** a recuperacao; o passo so acaba quando
    `pg_is_in_recovery()` e falso, que e quando a base aceita escritas.
    """
    f.inicio("replay", "arranque com o recovery.signal do pgBackRest ate pg_is_in_recovery() = f")
    ensaio.docker("exec", "-u", "postgres", novo, "pg_ctl", "-D", PGDATA, "-w", "-t", "7200",
                  "-l", "/tmp/postgres.log", "start", tempo=7300)
    while True:
        r = ensaio.docker("exec", novo, "psql", "-U", ADMIN, "-d", BASE, "-XAtqc",
                          "SELECT pg_is_in_recovery()", verificar=False)
        if r.returncode == 0 and r.stdout.strip() == "f":
            break
        ensaio._dormir(0.5)
    f.fim("replay")


def verificar_cadeia(ensaio: Ensaio, host: str, ancora: str | None = None) -> dict:
    """O `db/auditoria.py verificar` real, com o papel `batch`, contra o host restaurado."""
    comando = ["python", "auditoria.py", "verificar"]
    if ancora:
        comando += ["--ancora", ancora]
    r = ensaio.docker(
        "run", "--rm", "--network", REDE, "-e", "PYTHONDONTWRITEBYTECODE=1",
        "-e", "POSTGRES_PASSWORD", "-e", f"POSTGRES_USER={ADMIN}",
        "-e", f"KAMBA_DB_HOST={host}", "-e", f"KAMBA_DB_NAME={BASE}",
        *[parte for v in VARIAVEIS_DOS_PAPEIS for parte in ("-e", v)],
        "-v", f"{ensaio.raiz / 'db'}:/repo/db:ro", "-v", f"{ensaio.saida}:/out", "-w", "/repo/db",
        IMAGEM_CONDUTOR, *comando, verificar=False)
    return {"codigo": r.returncode, "saida": (r.stdout + r.stderr).strip()[-1500:]}


def passo_verificacao(ensaio: Ensaio, f: folha.Folha, novo: str,
                      antes: dict[str, int] | None) -> dict:
    f.inicio("verificacao", "contagens por tabela nas quatro bases, cadeia do audit_log, marcadores")
    depois = ensaio.contagens(novo)
    cadeia = verificar_cadeia(ensaio, novo)
    restaurados = ensaio.marcadores_restaurados(novo)
    f.fim("verificacao")
    divergentes = {}
    if antes is not None:
        for tabela, n in sorted(antes.items()):
            if tabela.endswith("dr_simulacro.marcador"):
                continue
            if depois.get(tabela) != n:
                divergentes[tabela] = {"antes": n, "depois": depois.get(tabela)}
    return {"contagens": depois, "contagens_divergentes": divergentes, "cadeia": cadeia,
            "restaurados": restaurados}


def _escritor(ensaio: Ensaio, pasta: str, host: str) -> str:
    nome = f"{PREFIXO}-marcadores-{pasta.lower()}"
    ensaio.docker("rm", "-f", nome, verificar=False)
    ensaio.condutor("python", "-m", "dr_simulacro.marcadores", "--host", host,
                    "--base", BASE, "--saida", f"/out/{pasta}/confirmados.csv",
                    "--erros", f"/out/{pasta}/erros.csv", "--parar", f"/out/{pasta}/parar",
                    nome=nome, destacado=True)
    return nome


def _parar(ensaio: Ensaio, pasta: Path, *nomes: str) -> None:
    (pasta / "parar").write_text("", encoding="utf-8")
    for nome in nomes:
        ensaio.docker("wait", nome, verificar=False, tempo=120)
        (pasta / f"{nome}.log").write_text(
            ensaio.docker("logs", nome, verificar=False).stdout, encoding="utf-8")
        ensaio.docker("rm", "-f", nome, verificar=False)


def _fechar(ensaio: Ensaio, cenario: str, pasta: Path, extra: dict,
            confirmados=None, restaurados=None) -> dict:
    lista = calculo.duracoes(folha.ler(pasta / "folha.jsonl"), cenario)
    rto = calculo.rto(lista)
    carga = {
        "cenario": cenario,
        "passos": [{"passo": d.passo, "segundos": d.segundos, "razao": d.razao} for d in lista],
        "rubricas": [{"rubrica": r.nome, "orcado_min": r.orcado_segundos / 60,
                      "medido_min": None if r.medido_segundos is None else r.medido_segundos / 60,
                      "por_medir": list(r.por_medir), "divergencia_pct": r.divergencia_pct}
                     for r in rto.rubricas],
        "rto_medido_min": rto.medido_segundos / 60,
        "rto_composto_min": rto.composto_segundos / 60,
        "lacunas_min": rto.lacunas_segundos / 60,
        "orcamento_no_composto": list(rto.orcamento_no_composto),
        "repetir_cenario_a": rto.repetir_cenario_a,
    }
    if confirmados and restaurados:
        r = calculo.rpo(confirmados, restaurados)
        carga["rpo"] = {"segundos": r.segundos, "perdidos": r.perdidos,
                        "sem_confirmacao": r.sem_confirmacao, "buracos": list(r.buracos),
                        "ultimo_confirmado": r.ultimo_confirmado,
                        "ultimo_restaurado": r.ultimo_restaurado,
                        "confirmados": len(confirmados), "restaurados": len(restaurados)}
    carga.update(extra)
    ensaio.registar(f"cenario-{cenario}", carga)
    return carga


# ---------------------------------------------------------------------------
# As fases
# ---------------------------------------------------------------------------


def preparar(ensaio: Ensaio, gib: float) -> dict:
    """A base sintetica de `gib` GiB, o backup completo e a exportacao do cofre."""
    ensaio.imagens()
    ensaio.rede()
    ensaio.docker("volume", "create", REPO_A)
    ensaio.primario(PRIMARIO_A, REPO_A, geracao=True)
    ensaio.esquema(PRIMARIO_A, TENANT)
    ensaio.auditar(PRIMARIO_A, TENANT, 1000, "antes-do-backup")
    carga = ensaio.carga(PRIMARIO_A, int(gib * 1024 ** 3))
    ensaio.reabrir_com_arquivo(PRIMARIO_A, REPO_A)
    ensaio.pgbackrest(PRIMARIO_A, "stanza-create")
    ensaio.pgbackrest(PRIMARIO_A, "check")
    contencao = ensaio.contencao()
    inicio = time.monotonic()
    ensaio.pgbackrest(PRIMARIO_A, "backup", "--type=full", tempo=14400)
    segundos_backup = time.monotonic() - inicio
    info = json.loads(ensaio.pgbackrest(PRIMARIO_A, "info", "--output=json"))
    exportacao = ensaio.exportacao_do_cofre(PRIMARIO_A)
    resultado = {"carga": carga, "backup_completo_segundos": segundos_backup,
                 "contencao_no_backup": contencao, "info": info, "exportacao": exportacao,
                 "repositorio_bytes": tamanho_em_bytes(ensaio.docker(
                     "exec", PRIMARIO_A, "du", "-sb", REPO_NO_CONTENTOR).stdout)}
    ensaio.registar("preparar", resultado)
    return resultado


def cenario_a(ensaio: Ensaio, segundos_de_escrita: float = 240) -> dict:
    """Perda do *host*: marcadores a 1/s, SIGKILL e disco perdido, restauro noutro host."""
    pasta = ensaio.saida / "A"
    pasta.mkdir(exist_ok=True)
    (pasta / "folha.jsonl").unlink(missing_ok=True)
    f = folha.Folha(pasta / "folha.jsonl", "A")
    escritor = _escritor(ensaio, "A", PRIMARIO_A)
    ensaio.auditar(PRIMARIO_A, TENANT, 200, "depois-do-backup")
    ensaio._dormir(segundos_de_escrita)
    sossego = ensaio.esperar_sossego()
    antes = ensaio.contagens(PRIMARIO_A)
    falha_em = agora()
    ensaio.matar(PRIMARIO_A)
    ensaio._dormir(5)
    _parar(ensaio, pasta, escritor)
    f.nao_medido("deteccao", "humano; e o alerta do WAL nao e servido por nenhum processo "
                             "(KAM-079, criterio 2): no ensaio a falha e conhecida por construcao")
    f.nao_medido("decisao", "humano: declarar o incidente e escolher o restauro (RB-K08)")
    novo = f"{PREFIXO}-restauro-a"
    contencao = passo_iac(ensaio, f, novo, REPO_A, com_cifra=True)
    pgdata = passo_restauro(ensaio, f, novo, ["pgbackrest", "--stanza=kamba", "restore"],
                            "pgbackrest restore ate ao fim do WAL arquivado; repositorio so de leitura",
                            contencao)
    passo_replay(ensaio, f, novo)
    verificacao = passo_verificacao(ensaio, f, novo, antes)
    f.nao_medido("dns", "nao ha DNS nem TTL configurados (KAM-075/D1)")
    confirmados = marcadores.ler_csv((pasta / "confirmados.csv").read_text(encoding="utf-8"))
    restaurados = verificacao.pop("restaurados")
    return _fechar(ensaio, "A", pasta, {
        "falha_em": falha_em, "pgdata_bytes": pgdata, "contencao": contencao,
        "sossego": sossego,
        "antes": antes, **verificacao}, confirmados, restaurados)


def cenario_c(ensaio: Ensaio) -> dict:
    """Cofre indisponivel: a passphrase do repositorio vem da exportacao offline cifrada.

    O host novo nasce **sem** `PGBACKREST_REPO1_CIPHER_PASS` no ambiente: e o
    cofre que nao responde. O passo `cofre` decifra a exportacao para
    `/dev/shm`, confere a contagem e entrega a passphrase ao restauro, e o
    ficheiro decifrado apaga-se antes de o pgBackRest arrancar.
    """
    pasta = ensaio.saida / "C"
    pasta.mkdir(exist_ok=True)
    (pasta / "folha.jsonl").unlink(missing_ok=True)
    f = folha.Folha(pasta / "folha.jsonl", "C")
    preparado = json.loads((ensaio.saida / "preparar.json").read_text(encoding="utf-8"))
    exportacao = preparado["exportacao"]
    a = json.loads((ensaio.saida / "cenario-A.json").read_text(encoding="utf-8"))
    f.nao_medido("deteccao", "nao se aplica: o C reaproveita a falha do A e o mesmo repositorio")
    f.nao_medido("decisao", "humano: declarar o cofre indisponivel e ir buscar a exportacao")
    novo = f"{PREFIXO}-restauro-c"
    sossego = ensaio.esperar_sossego()
    contencao = passo_iac(ensaio, f, novo, REPO_A, com_cifra=False)
    sem_cifra = ensaio.docker("exec", "-u", "postgres", novo, "pgbackrest", "--stanza=kamba",
                              "info", verificar=False)
    f.inicio("cofre", "sem cofre: decifrar a exportacao offline, conferir a contagem, "
                      "e por a passphrase num conf.d 0600 que o restore_command tambem le")
    # **A passphrase nao pode viver so no ambiente do `pgbackrest restore`.** A
    # primeira versao deste passo fazia isso, e o restauro passou e o arranque
    # falhou: o `restore_command` que o pgBackRest escreve no
    # `postgresql.auto.conf` e um `archive-get` que o *servidor* corre durante
    # a recuperacao, com o ambiente do servidor, e sem a passphrase nao decifra
    # um unico segmento de WAL. Por isso vai para o `conf.d`, que os dois leem.
    texto = ensaio.docker(
        "exec", "-i", "-u", "postgres", novo, "sh", "-c",
        "read -r P; umask 077; printf '%s' \"$P\" > /dev/shm/p; "
        "gpg --batch --quiet --pinentry-mode loopback --passphrase-file /dev/shm/p "
        f"--decrypt /offline/{exportacao['ficheiro']} > /dev/shm/cofre.json; rm -f /dev/shm/p; "
        f"{CONTAR_SEGREDOS}; mkdir -p /etc/pgbackrest/conf.d; "
        f"printf '[global]\\nrepo1-cipher-pass=%s\\n' \"$({EXTRAIR_PASSPHRASE})\" "
        "> /etc/pgbackrest/conf.d/cifra.conf; rm -f /dev/shm/cofre.json",
        entrada=ensaio.segredos["KAM085_OFFLINE_PASSPHRASE"] + "\n").stdout
    contagem = int(texto.strip().splitlines()[-1])
    if contagem < exportacao["segredos"]:
        raise EnsaioFalhou(f"exportacao incompleta: {contagem} < {exportacao['segredos']}")
    f.fim("cofre")
    pgdata = passo_restauro(ensaio, f, novo, ["pgbackrest", "--stanza=kamba", "restore"],
                            "pgbackrest restore com a passphrase da exportacao offline", contencao)
    passo_replay(ensaio, f, novo)
    verificacao = passo_verificacao(ensaio, f, novo, a["antes"])
    ensaio.docker("exec", novo, "rm", "-f", "/etc/pgbackrest/conf.d/cifra.conf")
    f.nao_medido("dns", "nao ha DNS nem TTL configurados (KAM-075/D1)")
    confirmados = marcadores.ler_csv((ensaio.saida / "A" / "confirmados.csv").read_text(encoding="utf-8"))
    restaurados = verificacao.pop("restaurados")
    return _fechar(ensaio, "C", pasta, {
        "sem_cifra_codigo": sem_cifra.returncode,
        "sem_cifra_saida": (sem_cifra.stdout + sem_cifra.stderr).strip()[-600:],
        "contagem_da_exportacao": contagem, "pgdata_bytes": pgdata, "contencao": contencao,
        "sossego": sossego,
        **verificacao}, confirmados, restaurados)


def _ancorar(ensaio: Ensaio, host: str, destino: str) -> str:
    """A ancora diaria real (`db/auditoria.py ancorar`), e o caminho do ficheiro."""
    pasta = ensaio.saida / "B" / destino
    pasta.mkdir(parents=True, exist_ok=True)
    ensaio.condutor("python", "auditoria.py", "ancorar", "--destino", f"/out/B/{destino}",
                    host=host)
    ficheiro = sorted(pasta.glob("*.json"))[-1]
    return f"/out/B/{destino}/{ficheiro.name}"


#: A margem antes de T na exportacao. **O `criado_at` do *outbox* e o inicio da
#: transaccao** (`DEFAULT now()`, revisao 0004), e nao o *commit*: um evento
#: cuja transaccao comecou antes de T e fez *commit* depois perde-se no PITR e
#: ficava fora de um filtro `>= T`. Exporta-se com folga e a reimportacao e
#: `ON CONFLICT DO NOTHING`, pelo que o que ja esta na base restaurada nao
#: entra duas vezes. Achado da revisao adversarial; o ensaio arquivado correu
#: com o filtro `>= T` e sem margem.
MARGEM_DA_EXPORTACAO = "5 minutes"

SQL_EXPORTAR_OUTBOX = """
COPY (SELECT event_id, tipo, versao, tenant_id, agregado_tipo, agregado_id, agregado_seq,
             particao, envelope, criado_at
        FROM platform.events_outbox
       WHERE tipo = '{tipo}'
         AND criado_at >= '{alvo}'::timestamptz - interval '{margem}'
       ORDER BY id)
  TO STDOUT WITH CSV;
"""
SQL_EXPORTAR_CONSUMIDOS = """
COPY (SELECT consumer, event_id, tenant_id, agregado_tipo, agregado_id, agregado_seq, processado_at
        FROM platform.events_consumed
       WHERE consumer = '{consumidor}'
         AND processado_at >= '{alvo}'::timestamptz - interval '{margem}')
  TO STDOUT WITH CSV;
"""


def preparar_b(ensaio: Ensaio, segundos_antes: float = 90, segundos_depois: float = 60) -> dict:
    """O cluster do B, a escrita, a migracao defeituosa, e a exportacao antes do PITR.

    Base pequena de proposito: o que o B mede e a **regra** do *outbox* depois
    de um PITR, e nao o debito, que e o do A. A migracao defeituosa vive
    **aqui** e nunca em `db/migrations/versions/`: e um `UPDATE` sem `WHERE`,
    o defeito de migracao mais comum que nao parte nenhum teste de esquema.
    """
    from .eventos import EXTERNO, TIPO

    pasta = ensaio.saida / "B"
    pasta.mkdir(exist_ok=True)
    ensaio.imagens()
    ensaio.rede()
    ensaio.docker("volume", "create", REPO_B)
    ensaio.primario(PRIMARIO_B, REPO_B)
    ensaio.esquema(PRIMARIO_B, TENANT)
    ensaio.auditar(PRIMARIO_B, TENANT, 300, "b-antes-do-backup")
    ensaio.pgbackrest(PRIMARIO_B, "stanza-create")
    ensaio.pgbackrest(PRIMARIO_B, "check")
    ensaio.pgbackrest(PRIMARIO_B, "backup", "--type=full")
    escritor = _escritor(ensaio, "B", PRIMARIO_B)
    produtor = f"{PREFIXO}-eventos-b"
    ensaio.docker("rm", "-f", produtor, verificar=False)
    ensaio.condutor("python", "-m", "dr_simulacro.eventos", "produzir", "--host", PRIMARIO_B,
                    "--base", BASE, "--tenant", TENANT, "--externos", "/out/B/externos.log",
                    "--parar", "/out/B/parar", nome=produtor, destacado=True)
    ensaio._dormir(segundos_antes)
    ensaio.auditar(PRIMARIO_B, TENANT, 100, "b-antes-do-erro")
    ancora_antes = _ancorar(ensaio, PRIMARIO_B, "ancora-antes")
    alvo = ensaio.instante_da_base(PRIMARIO_B)
    ensaio.psql(PRIMARIO_B, "-- migracao defeituosa injectada (so no ensaio)\n"
                            "UPDATE dr_simulacro.encomenda SET total_minor = 0;")
    ensaio._dormir(segundos_depois)
    ensaio.auditar(PRIMARIO_B, TENANT, 50, "b-depois-do-erro")
    ancora_depois = _ancorar(ensaio, PRIMARIO_B, "ancora-depois")
    _parar(ensaio, pasta, escritor, produtor)
    alvo_texto = folha.formatar(alvo)
    (pasta / "export-outbox.csv").write_text(ensaio.psql(
        PRIMARIO_B, SQL_EXPORTAR_OUTBOX.format(tipo=TIPO, alvo=alvo_texto,
                                               margem=MARGEM_DA_EXPORTACAO)), encoding="utf-8")
    (pasta / "export-consumidos.csv").write_text(ensaio.psql(
        PRIMARIO_B, SQL_EXPORTAR_CONSUMIDOS.format(consumidor=EXTERNO, alvo=alvo_texto,
                                                   margem=MARGEM_DA_EXPORTACAO)),
        encoding="utf-8")
    corrompidas = ensaio.psql(PRIMARIO_B, "SELECT count(*), count(*) FILTER (WHERE total_minor = 0) "
                                          "FROM dr_simulacro.encomenda;").strip()
    ensaio.psql(PRIMARIO_B, "SELECT pg_switch_wal();")
    ensaio.pgbackrest(PRIMARIO_B, "check")
    ensaio.docker("stop", PRIMARIO_B)
    resultado = {"alvo": alvo_texto, "ancora_antes": ancora_antes, "ancora_depois": ancora_depois,
                 "encomendas_no_primario_corrompido": corrompidas}
    ensaio.registar("preparar-b", resultado)
    return resultado


SQL_REIMPORTAR = """
CREATE TEMP TABLE o (event_id uuid, tipo text, versao smallint, tenant_id uuid, agregado_tipo text,
  agregado_id text, agregado_seq bigint, particao smallint, envelope jsonb, criado_at timestamptz);
CREATE TEMP TABLE c (consumer text, event_id uuid, tenant_id uuid, agregado_tipo text,
  agregado_id text, agregado_seq bigint, processado_at timestamptz);
\\copy o FROM '/tmp/export-outbox.csv' WITH CSV
\\copy c FROM '/tmp/export-consumidos.csv' WITH CSV
INSERT INTO platform.evt_agregado_seq (tenant_id, agregado_tipo, agregado_id, seq)
  SELECT tenant_id, agregado_tipo, agregado_id, max(agregado_seq) FROM o
   GROUP BY 1, 2, 3
  ON CONFLICT (tenant_id, agregado_tipo, agregado_id)
  DO UPDATE SET seq = GREATEST(platform.evt_agregado_seq.seq, EXCLUDED.seq);
INSERT INTO platform.events_outbox (event_id, tipo, versao, tenant_id, agregado_tipo, agregado_id,
  agregado_seq, particao, envelope, criado_at)
  SELECT * FROM o ON CONFLICT DO NOTHING;
INSERT INTO platform.events_consumed SELECT * FROM c ON CONFLICT DO NOTHING;
SELECT (SELECT count(*) FROM o), (SELECT count(*) FROM c);
"""


def cenario_b(ensaio: Ensaio, variante: str) -> dict:
    """PITR para antes do erro e *replay* do *outbox*; `b1` a letra, `b2` com a exportacao.

    `b1` e o procedimento como o §8.3 o escreve: PITR e republicar. `b2`
    acrescenta o passo que o B1 mostra em falta: reimportar, da exportacao
    feita **no primario corrompido antes do PITR**, os eventos posteriores a T
    e as marcas do consumidor com efeito externo.
    """
    from .eventos import TIPO

    preparado = json.loads((ensaio.saida / "preparar-b.json").read_text(encoding="utf-8"))
    alvo = folha.ler_instante(preparado["alvo"])
    pasta = ensaio.saida / variante.upper()
    pasta.mkdir(exist_ok=True)
    origem = ensaio.saida / "B"
    externos = pasta / "externos.log"
    externos.write_text((origem / "externos.log").read_text(encoding="utf-8"), encoding="utf-8")
    (pasta / "folha.jsonl").unlink(missing_ok=True)
    f = folha.Folha(pasta / "folha.jsonl", variante.upper())
    f.nao_medido("deteccao", "humano: quem nota o total a zero (no ensaio, 60 s depois do erro)")
    f.nao_medido("decisao", "humano: escolher o instante T a partir do registo da migracao")
    novo = f"{PREFIXO}-restauro-{variante}"
    contencao = passo_iac(ensaio, f, novo, REPO_B, com_cifra=True)
    alvo_pg = alvo.strftime("%Y-%m-%d %H:%M:%S.%f+00")
    pgdata = passo_restauro(
        ensaio, f, novo,
        ["pgbackrest", "--stanza=kamba", "restore", "--type=time", f"--target={alvo_pg}",
         "--target-action=promote"],
        f"PITR para T = {alvo_pg} (instante lido na base antes da migracao)", contencao)
    passo_replay(ensaio, f, novo)
    verificacao = passo_verificacao(ensaio, f, novo, None)
    reimportados = None
    if variante == "b2":
        for nome in ("export-outbox.csv", "export-consumidos.csv"):
            ensaio.docker("cp", str(origem / nome), f"{novo}:/tmp/{nome}")
        reimportados = ensaio.psql(novo, SQL_REIMPORTAR).strip()
    # O que o `retomar` republicou conta-se: um «0 duplicados» sobre zero
    # eventos republicados e uma prova vazia (achado da revisao adversarial).
    retomado = ensaio.condutor("python", "-m", "dr_simulacro.eventos", "retomar", "--host", novo,
                    "--base", BASE, "--tenant", TENANT,
                    "--externos", f"/out/{variante.upper()}/externos.log",
                    "--parar", f"/out/{variante.upper()}/parar")
    f.nao_medido("dns", "nao ha DNS nem TTL configurados (KAM-075/D1)")

    internos = ensaio.psql(novo, "SELECT event_id FROM dr_simulacro.efeito;").split()
    no_outbox = set(ensaio.psql(novo, f"SELECT event_id FROM platform.events_outbox "
                                      f"WHERE tipo = '{TIPO}';").split())
    linhas_externas = [l.split(",")[0] for l in externos.read_text(encoding="utf-8").splitlines() if l]
    exportados = [l.split(",")[0] for l in
                  (origem / "export-outbox.csv").read_text(encoding="utf-8").splitlines() if l]
    encomendas = ensaio.psql(novo, "SELECT count(*), count(*) FILTER (WHERE total_minor = 0) "
                                   "FROM dr_simulacro.encomenda;").strip()
    confirmados = marcadores.ler_csv((origem / "confirmados.csv").read_text(encoding="utf-8"))
    restaurados = verificacao.pop("restaurados")
    prova = calculo.prova_pitr(confirmados, restaurados, alvo)
    ancoras = {
        "antes_de_T": verificar_cadeia(ensaio, novo, preparado["ancora_antes"]),
        "depois_de_T": verificar_cadeia(ensaio, novo, preparado["ancora_depois"]),
    }
    return _fechar(ensaio, variante.upper(), pasta, {
        "alvo": preparado["alvo"], "pgdata_bytes": pgdata, "contencao": contencao,
        "reimportados": reimportados,
        "retomar": retomado.strip().splitlines()[-1] if retomado.strip() else "",
        "efeitos_internos": len(internos),
        "duplicados_internos": calculo.duplicados(internos),
        "efeitos_externos": len(linhas_externas),
        "duplicados_externos": calculo.duplicados(linhas_externas),
        "orfaos_externos": sorted(set(linhas_externas) - no_outbox),
        "eventos_exportados": len(exportados),
        "eventos_perdidos": sorted(set(exportados) - no_outbox),
        "encomendas_restauradas": encomendas,
        "encomendas_no_primario_corrompido": preparado["encomendas_no_primario_corrompido"],
        "pitr": {"provado": prova.provado, "anteriores_em_falta": list(prova.anteriores_em_falta),
                 "posteriores_presentes": list(prova.posteriores_presentes),
                 "na_fronteira": list(prova.na_fronteira)},
        "ancoras": ancoras,
        **verificacao}, confirmados, restaurados)


def pid1(ensaio: Ensaio, segundos: float = 180, intervalo: float = 15) -> dict:
    """O controlo do achado do PID 1: o mesmo arquivo a falhar, com e sem `--init`.

    Dois primarios com a configuracao de git e um repositorio **sem stanza**,
    pelo que cada `archive-push` falha — o mesmo que acontece com um `repo1`
    inalcancavel. A unica diferenca entre os dois e o `--init`. Forca-se uma
    mudanca de segmento a cada `intervalo` para nao esperar pelo
    `archive_timeout`, e contam-se, no registo de cada um, os reinicios do
    cluster inteiro.
    """
    ensaio.imagens()
    ensaio.rede()
    variantes = {"sem_init": False, "com_init": True}
    for rotulo, init in variantes.items():
        nome = f"{PREFIXO}-pid1-{rotulo.replace('_', '-')}"
        ensaio.matar(nome)
        ensaio.docker("volume", "rm", "-f", f"{nome}-repo", verificar=False)
        ensaio.docker("volume", "create", f"{nome}-repo")
        ensaio.primario(nome, f"{nome}-repo", init=init)
        ensaio.psql(nome, "CREATE TABLE IF NOT EXISTS pid1 (n bigint);")
    fim = time.monotonic() + segundos
    while time.monotonic() < fim:
        for rotulo in variantes:
            nome = f"{PREFIXO}-pid1-{rotulo.replace('_', '-')}"
            ensaio.docker("exec", nome, "psql", "-U", ADMIN, "-d", BASE, "-XAtqc",
                          "INSERT INTO pid1 VALUES (1); SELECT pg_switch_wal();", verificar=False)
        ensaio._dormir(intervalo)
    resultado = {"segundos": segundos, "intervalo": intervalo}
    for rotulo in variantes:
        nome = f"{PREFIXO}-pid1-{rotulo.replace('_', '-')}"
        registo = ensaio.docker("logs", nome, verificar=False)
        texto = registo.stdout + registo.stderr
        (ensaio.saida / f"pid1-{rotulo}.log").write_text(texto, encoding="utf-8")
        resultado[rotulo] = {
            "reinicios_do_cluster": texto.count("all server processes terminated; reinitializing"),
            "filhos_nao_seguidos": texto.count("untracked child process"),
            "archive_falhado": texto.count("archive command failed"),
        }
        ensaio.matar(nome)
        ensaio.docker("volume", "rm", "-f", f"{nome}-repo", verificar=False)
    ensaio.registar("pid1", resultado)
    return resultado


def limpar(ensaio: Ensaio) -> None:
    lista = ensaio.docker("ps", "-aq", "--filter", f"name={PREFIXO}-").stdout.split()
    if lista:
        ensaio.docker("rm", "-f", *lista, verificar=False)
    volumes = ensaio.docker("volume", "ls", "-q", "--filter", f"name={PREFIXO}-").stdout.split()
    if volumes:
        ensaio.docker("volume", "rm", "-f", *volumes, verificar=False)
    ensaio.docker("network", "rm", REDE, verificar=False)
    (ensaio.saida / "segredos.json").unlink(missing_ok=True)
