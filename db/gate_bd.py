"""Gates de base de dados: 8 (migracoes) e 6 (isolamento de tenant).

    python db/gate_bd.py --suite tests               # gate 8
    python db/gate_bd.py --suite tests_identidade    # gate 8, segunda metade
    python db/gate_bd.py --suite tests_isolamento    # gate 6
    python db/gate_bd.py --suite tests_chr           # gate 8, o CHR (KAM-014)
    python db/gate_bd.py --suite tests_outbound      # gate 8, a saida (KAM-015)
    python db/gate_bd.py --suite tests_handoff       # gate 8, o handoff (KAM-019)
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
    # KAM-012: as mil insercoes concorrentes do criterio 3. Suite propria pela
    # mesma razao que a carga de eventos — custa minutos, e uma suite custa
    # isso por cada mutacao que a escolha.
    "tests_auditoria_carga",
    # KAM-009: a regra de consumo de limites (`platform.ten_consumir`) — as mil
    # chamadas paralelas do criterio 3, a idempotencia, a fronteira de mes com
    # relogio fixo e o isolamento da funcao. Suite propria e nao dentro de
    # `tests` pela mesma razao das duas acima: as mil paralelas custam, e cada
    # mutacao da revisao 0007 pagaria esse custo somado ao da suite inteira.
    "tests_ten",
    # KAM-013: a entrada de canal. Precisa de PostgreSQL **e** de fila, e corre
    # os processos de producao — `services/gwy/src/server.ts` e
    # `services/worker-canal/src/entrada.ts` — em vez de um programa de ensaio.
    # Suite propria e nao dentro de `tests` por duas razoes: levanta e para
    # processos HTTP, o que `tests` nao faz; e para a fila a meio, o que
    # deixaria as outras 387 asercoes a correr contra um Redis em baixo.
    "tests_entrada",
    # KAM-013: o perfil de carga do criterio 7 — 200 pedidos/s durante 60 s.
    # Suite propria pela mesma razao da carga de eventos: custa um minuto de
    # relogio, e cada mutacao que a escolhesse pagaria esse custo.
    "tests_entrada_carga",
    # KAM-014: o CHR. Corre o modulo TypeScript (`packages/core-ts/src/chr/`)
    # contra a base, com os **tres papeis verdadeiros** — `kamba_resolver`,
    # `kamba_identity` e `kamba_app` —, que e a unica forma de provar que o
    # `phone_number_id` de A nao devolve o contexto de B e que `kamba_app`
    # sozinho nao responde a pergunta. Nao precisa de fila: a porta do AGR e
    # uma interface, e o que ela faz com o *job* e KAM-025.
    "tests_chr",
    # KAM-015: a saida de canal. Corre o modulo TypeScript
    # (`packages/core-ts/src/outbound/`) contra a base **e** contra o servidor
    # Graph falso do KAM-024, que e a unica forma de provar as tres coisas que
    # nao se simulam: que duas chamadas com a mesma chave dao **uma** linha (a
    # unicidade e da base, nao do codigo), que um `delivered` seguido de um
    # `sent` fica `delivered` (a monotonia tem de sobreviver a concorrencia
    # real), e que o `pricing` de um estado fica guardado por mensagem. Nao
    # precisa de fila: a ordem por conversa prova-se com o registo do servidor
    # falso, e a fila de saida e do proprio adapter.
    "tests_outbound",
    # KAM-019: a passagem a humano. O que so aqui se prova, e nao se simula
    # contra uma base falsa: que cinco aberturas concorrentes deixam **uma**
    # linha (a idempotencia e da chave primaria derivada, nao do codigo), que a
    # mesma conta do provedor em dois tenants e **recusada pela base** (o furo
    # que o X-10 procura, e que a chave primaria sozinha nao fecha), que dois
    # `close` em paralelo escrevem uma vez so, e que a RLS esconde a passagem de
    # A do contexto de B. **Nao leva o `tools/meta-sim`** e nao precisa de fila:
    # o handoff nao fala com a Meta, e o provedor de atendimento entra por porta.
    "tests_handoff",
)
#: As que precisam tambem de uma fila.
SUITES_COM_FILA = (
    "tests_eventos",
    "tests_eventos_consumo",
    "tests_eventos_carga",
    "tests_entrada",
    "tests_entrada_carga",
)


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
            "KAMBA_SECRET_DB_AUDIT_PASSWORD": secrets.token_urlsafe(24),
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
