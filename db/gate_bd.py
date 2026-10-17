"""Gates de base de dados: 8 (migracoes) e 6 (isolamento de tenant).

    python db/gate_bd.py --suite tests               # gate 8
    python db/gate_bd.py --suite tests_identidade    # gate 8, segunda metade
    python db/gate_bd.py --suite tests_isolamento    # gate 6
    python db/gate_bd.py --suite tests --bd-existente

Os dois gates precisam do mesmo: um PostgreSQL real, vazio e descartavel. Este
ficheiro levanta-o e corre a suite pedida; o que cada gate prova esta nas
suites (`db/tests/`, `db/tests_identidade/` e `db/tests_isolamento/`). A base
chama-se `kamba_gate8` em todos os casos — o nome e o do trinco, e ficou do
primeiro gate que o usou.

`tests_identidade` (KAM-008) corre o modulo de identidade — TypeScript, em
`packages/core-ts` — contra a base, e precisa de saber em que contentor ela
esta, para lhe pedir o `pg_dump` e o registo do servidor: o nome vai em
`KAMBA_GATE_CONTENTOR`.

O gate precisa de um PostgreSQL **real** e **vazio**, e nao pode ser o de
desenvolvimento: a suite faz `downgrade base`, que apaga o schema `platform`.
Por isso o caminho por omissao levanta o seu proprio contentor:

- a mesma imagem do compose, **fixada por digest** — o criterio de aceitacao diz
  PostgreSQL 18.6, e uma etiqueta que flutue de *minor* deixava de o provar;
- dados em `tmpfs`: nada toca no disco e nada sobrevive;
- porta publicada so em `127.0.0.1`, escolhida pelo Docker;
- palavras-passe geradas nesta execucao: passam ao contentor e a suite pelo
  ambiente, nao pela linha de comandos, e nao se imprimem. (Ficam visiveis no
  `docker inspect` do contentor enquanto ele vive, como qualquer variavel de
  ambiente de um contentor; sao efemeras e a porta so escuta em 127.0.0.1.)

O contentor e removido no fim, corra a suite bem ou mal, e tambem quando o
processo recebe SIGINT ou SIGTERM. **Nao** quando e morto com SIGKILL: nesse
caso fica um `kamba-gate8-*` orfao, que se remove a mao.

`--bd-existente` existe para quando o Docker nao esta ao alcance do processo
(por exemplo, a correr ja dentro de um contentor, com a base noutro). Tem dois
trincos, e o segundo e o que importa:

- a base tem de se chamar `kamba_gate8`;
- as palavras-passe dos cinco papeis tem de vir **dadas** no ambiente. Os papeis
  sao globais a instancia, nao a base: o `bootstrap` redefine-lhes a
  palavra-passe, e gera-las aqui trocava as credenciais de todos os servicos da
  instancia por valores que ninguem conhece. Este modo so e seguro contra uma
  instancia descartavel; o trinco do nome protege a base, nao a instancia.
"""

from __future__ import annotations

import argparse
import os
import secrets
import signal
import subprocess
import sys
import time
from pathlib import Path

DB = Path(__file__).resolve().parent
sys.path.insert(0, str(DB))

# O digest da fila vive em `db/fila_do_gate.py`, e nao aqui: o
# `ci/supply-chain/imagens.yaml` aceita **uma** constante por ficheiro em
# `fontes_adicionais`, e este ja la esta com a `IMAGEM` do PostgreSQL.
import fila_do_gate  # noqa: E402

#: A imagem do compose de desenvolvimento, com o digest observado e registado
#: em `docs/evidencia/KAM-001-node.md` §3 (PostgreSQL 18.6, pgvector 0.8.7).
#: Desde o KAM-067 a fixacao e sistematica: esta constante esta declarada em
#: `ci/supply-chain/imagens.yaml` (`fontes_adicionais`), e `make supply-chain`
#: falha se o digest daqui deixar de ser o do inventario.
IMAGEM = (
    "pgvector/pgvector:0.8.7-pg18"
    "@sha256:2358fcba361ed2233a5ed81b5fe4ca779ccb304120ce531a3bf51c0ed7e2bc11"
)

BASE = "kamba_gate8"
ADMIN = "kamba"
ESPERA_MAXIMA = 90
#: Segundos. Num runner Linux a suite corre em poucos minutos; isto e folga
#: para uma maquina lenta ou partilhada (medido em Windows com Docker Desktop:
#: perto de dez minutos na suite `tests` antes de se poupar o Alembic em
#: `tests/base.py`), nao alvo.
TEMPO_MAXIMO_DA_SUITE = 900
#: As suites com fila levam mais: o criterio 4 para a fila 60 s de proposito e
#: o criterio 8 mede 5 minutos de carga. Sao tempos do **criterio**, nao folga.
TEMPO_MAXIMO_DOS_EVENTOS = 1500
#: As suites que este ficheiro sabe correr. Lista fechada.
SUITES = (
    "tests",
    "tests_identidade",
    "tests_isolamento",
    "tests_eventos",
    "tests_eventos_consumo",
    "tests_eventos_carga",
)
#: As que precisam tambem de uma fila.
SUITES_COM_FILA = ("tests_eventos", "tests_eventos_consumo", "tests_eventos_carga")


def _docker(*argumentos: str, ambiente=None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", *argumentos], capture_output=True, text=True, env=ambiente
    )


def _ambiente_da_suite(host: str, porta: str, senha_admin: str) -> dict[str, str]:
    ambiente = dict(os.environ)
    ambiente.update(
        {
            "KAMBA_DB_HOST": host,
            "KAMBA_DB_PORT": porta,
            "KAMBA_DB_NAME": BASE,
            "POSTGRES_USER": ADMIN,
            "POSTGRES_PASSWORD": senha_admin,
            "KAMBA_SECRET_DB_MIGRATOR_PASSWORD": secrets.token_urlsafe(24),
            "KAMBA_SECRET_DB_APP_PASSWORD": secrets.token_urlsafe(24),
            "KAMBA_SECRET_DB_BATCH_PASSWORD": secrets.token_urlsafe(24),
            "KAMBA_SECRET_DB_RESOLVER_PASSWORD": secrets.token_urlsafe(24),
            "KAMBA_SECRET_DB_IDENTITY_PASSWORD": secrets.token_urlsafe(24),
        }
    )
    return ambiente


def _esperar_pela_base(ambiente: dict[str, str]) -> None:
    """Espera ate a base aceitar ligacoes autenticadas.

    Nao basta o `pg_isready`: o entrypoint da imagem arranca o servidor uma
    primeira vez para o `initdb` e reinicia-o. Uma ligacao real, repetida, e a
    unica prova de que o que responde ja e o servidor definitivo.
    """
    sys.path.insert(0, str(DB))
    import ligacao

    limite = time.monotonic() + ESPERA_MAXIMA
    ultimo: Exception | None = None
    estaveis = 0
    while time.monotonic() < limite:
        try:
            conexao = ligacao.ligar("admin", ambiente)
            conexao.close()
            estaveis += 1
            if estaveis >= 3:
                return
        except Exception as erro:  # noqa: BLE001 — qualquer falha e «ainda nao»
            ultimo = erro
            estaveis = 0
        time.sleep(1)
    raise RuntimeError(
        f"a base nao ficou disponivel em {ESPERA_MAXIMA}s: {type(ultimo).__name__}"
    )


def _correr_suite(ambiente: dict[str, str], suite: str) -> int:
    # Pelo `correr_suite.py` e nao por `python -m unittest`: este sai com 0
    # quando todos os testes sao saltados, e o trinco da suite salta. Num gate,
    # saltar e falhar.
    limite = (
        TEMPO_MAXIMO_DOS_EVENTOS if suite in SUITES_COM_FILA else TEMPO_MAXIMO_DA_SUITE
    )
    try:
        return subprocess.run(
            [sys.executable, "correr_suite.py", suite],
            cwd=DB,
            env=ambiente,
            timeout=limite,
        ).returncode
    except subprocess.TimeoutExpired:
        # Um gate pendurado e pior do que um gate vermelho: ocupa o runner ate
        # ao limite do job e nao diz porque. Passar da folga e um bloqueio, e
        # diz-se.
        print(
            f"gate de BD: a suite nao terminou em {limite}s. "
            "Provavelmente um bloqueio entre ligacoes (um teste a fazer DDL com "
            "outra transaccao aberta).",
            file=sys.stderr,
        )
        return 1


def com_contentor(suite: str) -> int:
    senha_admin = secrets.token_urlsafe(24)
    sufixo = secrets.token_hex(4)
    nome = f"kamba-gate8-{sufixo}"
    com_fila = suite in SUITES_COM_FILA
    # A rede so se cria quando faz falta: o caminho das outras tres suites fica
    # exactamente como estava.
    rede = f"kamba-eventos-{sufixo}" if com_fila else ""
    ambiente_docker = dict(os.environ)
    ambiente_docker.update(
        {"POSTGRES_USER": ADMIN, "POSTGRES_PASSWORD": senha_admin, "POSTGRES_DB": BASE}
    )
    if com_fila:
        criacao = _docker("network", "create", rede)
        if criacao.returncode != 0:
            print(f"gate de BD: nao foi possivel criar a rede:\n{criacao.stderr}",
                  file=sys.stderr)
            return 2
    arranque = _docker(
        "run", "--detach", "--rm", "--name", nome,
        # Sem valor: o Docker le-as do ambiente deste processo, pelo que a
        # palavra-passe nao aparece na linha de comandos (nem em `ps`).
        "--env", "POSTGRES_USER", "--env", "POSTGRES_PASSWORD", "--env", "POSTGRES_DB",
        "--env", "POSTGRES_INITDB_ARGS=--auth-host=scram-sha-256",
        "--tmpfs", "/var/lib/postgresql",
        "--publish", "127.0.0.1::5432",
        *(("--network", rede) if com_fila else ()),
        IMAGEM,
        ambiente=ambiente_docker,
    )
    if arranque.returncode != 0:
        print(f"gate de BD: nao foi possivel arrancar o PostgreSQL:\n{arranque.stderr}",
              file=sys.stderr)
        if com_fila:
            _docker("network", "rm", rede)
        return 2
    fila = ""
    try:
        porta = _docker("port", nome, "5432/tcp").stdout.strip().rsplit(":", 1)[-1]
        if not porta.isdigit():
            print("gate de BD: o Docker nao devolveu a porta publicada", file=sys.stderr)
            return 2
        ambiente = _ambiente_da_suite("127.0.0.1", porta, senha_admin)
        # Para a suite de identidade: e pelo contentor que se pede o `pg_dump`
        # e o registo do servidor.
        ambiente["KAMBA_GATE_CONTENTOR"] = nome
        if com_fila:
            fila = f"kamba-fila-{sufixo}"
            porta_da_fila = fila_do_gate.arrancar(rede, fila)
            ambiente.update(
                {
                    "KAMBA_GATE_FILA": fila,
                    "KAMBA_GATE_REDE": rede,
                    "KAMBA_FILA_HOST": "127.0.0.1",
                    "KAMBA_FILA_PORT": porta_da_fila,
                    # O publicador corre em Node, dentro da rede: chega a base e
                    # a fila pelo nome do contentor, nao pela porta publicada.
                    "KAMBA_QUEUE_URL": f"redis://{fila}:6379",
                    "KAMBA_DB_HOST_NA_REDE": nome,
                }
            )
        _esperar_pela_base(ambiente)
        return _correr_suite(ambiente, suite)
    except RuntimeError as erro:
        print(f"gate de BD: {erro}", file=sys.stderr)
        registo = _docker("logs", "--tail", "20", nome)
        print(registo.stdout + registo.stderr, file=sys.stderr)
        return 2
    finally:
        if fila:
            _docker("rm", "--force", fila)
        _docker("rm", "--force", nome)
        if com_fila:
            _docker("network", "rm", rede)


def com_bd_existente(suite: str) -> int:
    if os.environ.get("KAMBA_DB_NAME", "") != BASE:
        print(
            f"gate de BD: --bd-existente exige KAMBA_DB_NAME={BASE}. O gate apaga o "
            "schema `platform` e so corre contra a base descartavel.",
            file=sys.stderr,
        )
        return 2
    ambiente = dict(os.environ)
    em_falta = [
        f"KAMBA_SECRET_DB_{papel}_PASSWORD"
        for papel in ("MIGRATOR", "APP", "BATCH", "RESOLVER", "IDENTITY")
        if not ambiente.get(f"KAMBA_SECRET_DB_{papel}_PASSWORD")
    ]
    if em_falta:
        print(
            "gate de BD: --bd-existente exige as palavras-passe dos cinco papeis no "
            f"ambiente; faltam: {', '.join(em_falta)}.\n"
            "    Os papeis sao globais a instancia: gera-las aqui trocava as "
            "credenciais de todos os servicos que a usam.",
            file=sys.stderr,
        )
        return 2
    try:
        _esperar_pela_base(ambiente)
    except RuntimeError as erro:
        print(f"gate de BD: {erro}", file=sys.stderr)
        return 2
    return _correr_suite(ambiente, suite)


def _sair_com_limpeza(numero, _quadro) -> None:
    """SIGINT/SIGTERM passam a excepcao, para os `finally` correrem."""
    raise SystemExit(128 + numero)


def main(argv: list[str] | None = None) -> int:
    for sinal in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sinal, _sair_com_limpeza)
    analisador = argparse.ArgumentParser(prog="gate_bd", description=__doc__.split("\n")[0])
    analisador.add_argument(
        "--suite",
        choices=SUITES,
        default="tests",
        help="tests e tests_identidade (gate 8) ou tests_isolamento (gate 6)",
    )
    analisador.add_argument(
        "--bd-existente",
        action="store_true",
        help=f"usa a base apontada pelo ambiente (tem de se chamar {BASE})",
    )
    argumentos = analisador.parse_args(argv)
    if argumentos.bd_existente:
        return com_bd_existente(argumentos.suite)
    return com_contentor(argumentos.suite)


if __name__ == "__main__":
    sys.exit(main())
