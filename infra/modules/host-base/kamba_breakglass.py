#!/usr/bin/python3 -I
"""O portao do acesso de excepcao a um host da KAMBA (KAM-259).

Decisao do fundador de 2026-11-25, opcao A. A conta `breakglass` entra por SSH e
o `sshd` corre **sempre** este programa: ele e a *shell* de login da conta, e o
`ForceCommand` do `sshd` aponta para ele (`cloud-init.yaml.tftpl`). Corre em
duas fases:

    entrada   como `breakglass`, sem fazer nada alem de `exec` do
              `sudo -n <programa> sessao` — o unico comando que o `sudoers` da
              conta autoriza, sem argumentos variaveis.
    sessao    como root:
                1. le o pedido: quem (a impressao digital da chave com que a
                   sessao entrou), onde (o ambiente e o host), porque (a razao)
                   e ate quando (o prazo, obrigatorio, no maximo sete dias), e
                   da a sessao um identificador proprio;
                2. escreve `breakglass.open` no `audit_log` pelo `psql` do
                   contentor da base, e espera pelo fim da escrita;
                3. **so depois** abre a *shell* como `breakglass`, num *scope*
                   do systemd com tempo limite no prazo;
                4. quando a *shell* fecha — por saida, por prazo ou por sinal —
                   para o *scope* (e com ele tudo o que a sessao lancou) e
                   escreve `breakglass.close`.

Se o passo 2 falhar, a sessao sai com 69 e **sem shell**: e a falha fechada que
o criterio 3 do bloco pede. O passo 4 corre num `finally`, num processo de root
que a *shell* da conta nao pode sinalizar.

O `-I` da primeira linha e parte do portao: o Python isolado nao le o
`PYTHONPATH` nem os `site-packages` da casa da conta.

## Como se pede

    ssh -t breakglass@<host> '<prazo ISO 8601 com fuso> <razao>'

    ssh -t breakglass@<host> '2026-12-01T18:00:00+01:00 revisao independente, area 6'

O portao responde com o identificador da sessao e o prazo, que quem pediu
regista com a razao (para o revisor do KAM-074, no `relatorio.md` §2).

## Quem escreve a linha

O papel `kamba_breakglass` (revisao `0093`), cuja credencial esta num ficheiro so
de root, pela porta `platform.breakglass_registar`. O papel so escreve as duas
accoes de *break-glass* na cadeia de plataforma.

## Estado

O nucleo (`sessao`, `validar`, `resumo`, `impressao_digital`) e a escrita pelo
`psql` do contentor da base (`gravar_pelo_psql`, o mesmo `docker exec` que o
host corre) estao ensaiados contra um PostgreSQL real em
`db/tests/test_breakglass.py`. O que so existe num host — o `sshd`, o `sudo`,
o `systemd-run` e a conta — **NAO FOI VERIFICADO**, porque nenhum host existe
ainda (`infra/README.md` §5), como o resto do `host-base`.

So biblioteca padrao: o host nao tem dependencias Python da KAMBA.
"""

from __future__ import annotations

import base64
import dataclasses
import hashlib
import json
import os
import re
import signal
import socket
import subprocess
import sys
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

#: As duas accoes do dominio de `audit_log.action` (revisao `0093`).
ACCAO_ABRIR = "breakglass.open"
ACCAO_FECHAR = "breakglass.close"
ACCOES = (ACCAO_ABRIR, ACCAO_FECHAR)

#: O tecto do prazo: decisao do fundador de 2026-11-25.
TECTO = timedelta(days=7)

#: Os ambientes onde a conta existe. `dev` nao tem host.
AMBIENTES = ("staging", "prod")

#: A razao entra so no `payload_hash`, nunca em claro na base. O tecto impede
#: que um pedido traga um texto arbitrariamente grande.
RAZAO_MAXIMA = 500

#: O `entity_id` e `<ambiente>/<host>`, e o `audit_log` limita-o a 256.
TECTO_DO_TEXTO = 256

#: A porta da base. `%s`, que e o estilo do `pg8000` e do `psycopg`.
SQL_REGISTAR = "SELECT platform.breakglass_registar(%s, %s, %s, %s)"

#: A mesma chamada, para o `psql`: as variaveis `:'x'` sao citadas pelo proprio
#: `psql`, e nenhum argumento e concatenado no texto.
SQL_DO_PSQL = (
    "SELECT platform.breakglass_registar("
    ":'accao', :'actor', :'host', decode(:'resumo', 'hex'));\n"
)

#: O papel com que o `psql` entra.
PAPEL = "kamba_breakglass"

#: A conta, e onde o portao vive no host.
CONTA = "breakglass"
PROGRAMA = "/usr/local/sbin/kamba-breakglass"
SUDO = "/usr/bin/sudo"

#: Onde o portao le a configuracao (escrita pelo `cloud-init`, so de root).
CONFIGURACAO = "/etc/kamba/breakglass.env"
#: O ficheiro que diz que host e este (`cloud-init`, KAM-075).
FICHEIRO_DO_AMBIENTE = "/etc/kamba/ambiente"

#: Quanto se le do ficheiro do `ExposeAuthInfo`: chega para uma chave.
LEITURA_MAXIMA = 64 * 1024

#: Codigos de saida (`sysexits.h`).
SAIDA_PEDIDO_INVALIDO = 64
SAIDA_SEM_REGISTO = 69
SAIDA_FECHO_SEM_REGISTO = 70

_HEX = re.compile(r"^[0-9a-f]{64}$")
_SESSAO = re.compile(r"^[0-9a-f]{32}$")


class PedidoInvalido(ValueError):
    """O pedido nao passa: a sessao sai sem escrever nada e sem shell."""


@dataclasses.dataclass(frozen=True)
class Pedido:
    actor: str
    ambiente: str
    host: str
    razao: str
    prazo: datetime
    #: O identificador da sessao: distingue duas sessoes do mesmo pedido.
    sessao: str

    @property
    def entidade(self) -> str:
        """O `entity_id` da linha: o ambiente e o host."""
        return f"{self.ambiente}/{self.host}"


#: `gravar(accao, actor, entity_id, payload_hash)`; levanta se nao escreveu.
Gravar = Callable[[str, str, str, bytes], None]
#: `abrir_shell(segundos)` -> codigo de saida da shell.
AbrirShell = Callable[[float], int]


def agora_utc() -> datetime:
    return datetime.now(timezone.utc)


def nova_sessao() -> str:
    return uuid.uuid4().hex


def impressao_digital(info_de_autenticacao: str) -> str:
    """A impressao `SHA256:` da chave com que a sessao entrou.

    Le o ficheiro do `ExposeAuthInfo` do `sshd` (`SSH_USER_AUTH`), cujas
    linhas sao `publickey <tipo> <base64> [comentario]`. A impressao e a do
    `ssh-keygen -l`: SHA-256 do *blob* da chave, em base64 sem `=`. O nome da
    pessoa nao entra: a correspondencia impressao -> pessoa vive fora do
    repositorio, com as chaves.
    """
    for linha in info_de_autenticacao.splitlines():
        partes = linha.split()
        if len(partes) >= 3 and partes[0] == "publickey":
            try:
                blob = base64.b64decode(partes[2], validate=True)
            except ValueError as erro:
                raise PedidoInvalido("a chave da sessao nao e base64") from erro
            digest = base64.b64encode(hashlib.sha256(blob).digest()).decode("ascii")
            return "SHA256:" + digest.rstrip("=")
    raise PedidoInvalido("a sessao nao entrou por chave publica")


def ler_comando(comando: str) -> tuple[datetime, str]:
    """`'<prazo> <razao>'` -> (prazo, razao). O prazo leva fuso."""
    partes = (comando or "").strip().split(None, 1)
    if len(partes) != 2:
        raise PedidoInvalido(
            "pede-se assim: ssh -t breakglass@<host> '<prazo ISO 8601 com fuso> <razao>'"
        )
    try:
        prazo = datetime.fromisoformat(partes[0])
    except ValueError as erro:
        raise PedidoInvalido(f"prazo ilegivel: {partes[0]!r}") from erro
    return prazo, partes[1].strip()


def validar(pedido: Pedido, agora: datetime) -> None:
    """Recusa o pedido antes de escrever seja o que for."""
    if pedido.ambiente not in AMBIENTES:
        raise PedidoInvalido(f"ambiente sem break-glass: {pedido.ambiente!r}")
    if not pedido.host or "/" in pedido.host or any(c.isspace() for c in pedido.host):
        raise PedidoInvalido("o host tem de ser um nome sem espacos nem barras")
    if len(pedido.entidade) > TECTO_DO_TEXTO:
        raise PedidoInvalido("o nome do host e demasiado longo")
    if not pedido.actor or len(pedido.actor) > TECTO_DO_TEXTO:
        raise PedidoInvalido("sem actor")
    if not _SESSAO.match(pedido.sessao or ""):
        raise PedidoInvalido("sem identificador de sessao")
    if not pedido.razao:
        raise PedidoInvalido("a razao e obrigatoria")
    if len(pedido.razao) > RAZAO_MAXIMA:
        raise PedidoInvalido(f"a razao tem no maximo {RAZAO_MAXIMA} caracteres")
    if pedido.prazo.tzinfo is None:
        raise PedidoInvalido("o prazo leva fuso horario (por exemplo +01:00)")
    if pedido.prazo <= agora:
        raise PedidoInvalido("o prazo ja passou")
    if pedido.prazo > agora + TECTO:
        raise PedidoInvalido("o prazo passa o tecto de sete dias")


def resumo(pedido: Pedido) -> bytes:
    """O `payload_hash` das duas linhas da sessao.

    SHA-256 de uma lista JSON montada campo a campo, por ordem fixa, com o
    prazo em UTC. A razao so existe aqui: a base guarda o hash, que e o que o
    `docs/tecnica/08` §7.1 manda para o `audit_log`. As duas linhas da mesma
    sessao levam o mesmo resumo, e o identificador da sessao faz com que duas
    sessoes do mesmo pedido levem resumos diferentes.
    """
    prazo = pedido.prazo.astimezone(timezone.utc).isoformat(timespec="seconds")
    campos = [pedido.sessao, pedido.actor, pedido.ambiente, pedido.host, pedido.razao, prazo]
    texto = json.dumps(campos, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(texto.encode("utf-8")).digest()


class _Sinal(Exception):
    """Um SIGHUP ou SIGTERM a meio da sessao: sai pelo `finally` e regista o fecho."""


def _ao_sinal(numero, _quadro):  # pragma: no cover - exercitado num host
    raise _Sinal(numero)


def sessao(
    pedido: Pedido,
    gravar: Gravar,
    abrir_shell: AbrirShell,
    agora: Callable[[], datetime] = agora_utc,
    erro=sys.stderr,
) -> int:
    """Uma sessao de break-glass. Devolve o codigo de saida.

    **A ordem e o produto**: o `gravar` da abertura tem de voltar sem erro
    antes de o `abrir_shell` ser chamado. Uma excepcao na escrita da abertura
    devolve `SAIDA_SEM_REGISTO` sem nunca chamar a shell.
    """
    try:
        validar(pedido, agora())
    except PedidoInvalido as motivo:
        print(f"break-glass recusado: {motivo}", file=erro)
        return SAIDA_PEDIDO_INVALIDO

    payload = resumo(pedido)
    try:
        gravar(ACCAO_ABRIR, pedido.actor, pedido.entidade, payload)
    except Exception as falha:  # noqa: BLE001 - qualquer falha fecha a porta
        print(
            f"break-glass recusado: a escrita no audit_log falhou ({type(falha).__name__}); "
            "sem a linha nao ha shell",
            file=erro,
        )
        return SAIDA_SEM_REGISTO

    print(
        f"break-glass: sessao {pedido.sessao} aberta ate {pedido.prazo.isoformat()}",
        file=erro,
    )
    codigo = 0
    try:
        restante = (pedido.prazo - agora()).total_seconds()
        codigo = abrir_shell(max(restante, 0.0))
    except _Sinal:  # pragma: no cover - exercitado num host
        codigo = 129
    finally:
        try:
            gravar(ACCAO_FECHAR, pedido.actor, pedido.entidade, payload)
        except Exception as falha:  # noqa: BLE001
            print(
                f"break-glass: a escrita do fecho falhou ({type(falha).__name__})",
                file=erro,
            )
            codigo = SAIDA_FECHO_SEM_REGISTO
    return codigo


def gravar_por_ligacao(ligar: Callable[[], object]) -> Gravar:
    """Um `Gravar` sobre uma ligacao DB-API do `kamba_breakglass`.

    Uma ligacao por linha, e o `commit` antes de voltar: a linha esta escrita
    quando a funcao volta, e nao quando alguem mais tarde fizer `commit`.
    """

    def gravar(accao: str, actor: str, entidade: str, payload: bytes) -> None:
        conexao = ligar()
        try:
            cursor = conexao.cursor()
            cursor.execute(SQL_REGISTAR, (accao, actor, entidade, payload))
            conexao.commit()
        finally:
            conexao.close()

    return gravar


def comando_do_psql(contentor: str, base: str, accao: str, actor: str,
                    entidade: str, payload: bytes) -> list[str]:
    """O `docker exec ... psql` de uma linha. A palavra-passe vai por ambiente."""
    if (
        accao not in ACCOES
        or not actor
        or len(actor) > TECTO_DO_TEXTO
        or not entidade
        or len(entidade) > TECTO_DO_TEXTO
        or not _HEX.match(payload.hex())
    ):
        raise PedidoInvalido("argumentos da escrita recusados")
    return [
        "docker", "exec", "-i", "-e", "PGPASSWORD", contentor,
        "psql", "-X", "-q", "-v", "ON_ERROR_STOP=1", "-h", "127.0.0.1",
        "-U", PAPEL, "-d", base,
        "-v", f"accao={accao}", "-v", f"actor={actor}",
        "-v", f"host={entidade}", "-v", f"resumo={payload.hex()}",
    ]


def gravar_pelo_psql(contentor: str, base: str, senha: str, executar=subprocess.run) -> Gravar:
    """O `Gravar` do host: o `psql` de dentro do contentor da base, com `check`.

    O `ON_ERROR_STOP` e o `check` sao os dois que fazem de uma recusa da base
    uma excepcao aqui: sem o primeiro o `psql` sai com 0 depois de um erro, e
    sem o segundo um codigo diferente de 0 nao levanta.
    """

    def gravar(accao: str, actor: str, entidade: str, payload: bytes) -> None:
        executar(
            comando_do_psql(contentor, base, accao, actor, entidade, payload),
            input=SQL_DO_PSQL,
            text=True,
            env=dict(os.environ, PGPASSWORD=senha),
            stdout=subprocess.DEVNULL,
            timeout=30,
            check=True,
        )

    return gravar


def _ler_env(caminho: str) -> dict[str, str]:  # pragma: no cover - host
    valores: dict[str, str] = {}
    with open(caminho, encoding="utf-8") as ficheiro:
        for linha in ficheiro:
            linha = linha.strip()
            if linha and not linha.startswith("#") and "=" in linha:
                chave, valor = linha.split("=", 1)
                valores[chave.strip()] = valor.strip()
    return valores


def _ambiente_do_host() -> str:  # pragma: no cover - host
    with open(FICHEIRO_DO_AMBIENTE, encoding="utf-8") as ficheiro:
        for linha in ficheiro:
            if linha.startswith("KAMBA_ENV="):
                return linha.split("=", 1)[1].strip()
    return ""


def _abridor_de_shell(identificador: str, terminal: str) -> AbrirShell:  # pragma: no cover - host
    """A shell da conta, num *scope* do systemd que se para no fim.

    O *scope* e o que mata o que a sessao lancou e deixou a correr (um
    `nohup`, um `setsid`), e o `RuntimeMaxSec` e um segundo limite ao prazo,
    do lado do systemd. NAO VERIFICADO num host.
    """
    unidade = f"kamba-breakglass-{identificador}"

    def abrir(segundos: float) -> int:
        try:
            return subprocess.run(
                [
                    "systemd-run", "--scope", "--quiet", "--collect", "--unit", unidade,
                    "-p", f"RuntimeMaxSec={max(int(segundos), 1)}",
                    "--uid", CONTA, "--gid", CONTA,
                    "/usr/bin/env", "-i", f"HOME=/home/{CONTA}", f"USER={CONTA}",
                    f"LOGNAME={CONTA}", f"TERM={terminal}",
                    "PATH=/usr/local/bin:/usr/bin:/bin", "/bin/bash", "-l",
                ],
                cwd=f"/home/{CONTA}",
                timeout=segundos,
            ).returncode
        except subprocess.TimeoutExpired:
            print("break-glass: prazo atingido; sessao fechada", file=sys.stderr)
            return 124
        finally:
            subprocess.run(
                ["systemctl", "stop", f"{unidade}.scope"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
            )

    return abrir


def principal(argumentos: list[str]) -> int:  # pragma: no cover - host
    if os.geteuid() != 0:
        # Fase de entrada: o `sshd` chama a shell de login (`<programa> -c
        # <ForceCommand>`). Nao se le nada do que veio: so o `exec` do unico
        # comando que o `sudoers` da conta autoriza.
        os.execv(SUDO, [SUDO, "-n", PROGRAMA, "sessao"])
    if argumentos != ["sessao"]:
        print("break-glass recusado: chamada inesperada", file=sys.stderr)
        return SAIDA_PEDIDO_INVALIDO
    signal.signal(signal.SIGHUP, _ao_sinal)
    signal.signal(signal.SIGTERM, _ao_sinal)
    try:
        with open(os.environ.get("SSH_USER_AUTH", ""), encoding="utf-8") as ficheiro:
            actor = impressao_digital(ficheiro.read(LEITURA_MAXIMA))
        prazo, razao = ler_comando(os.environ.get("SSH_ORIGINAL_COMMAND", ""))
        config = _ler_env(CONFIGURACAO)
    except (OSError, PedidoInvalido) as motivo:
        print(f"break-glass recusado: {motivo}", file=sys.stderr)
        return SAIDA_PEDIDO_INVALIDO
    identificador = nova_sessao()
    pedido = Pedido(
        actor=actor,
        ambiente=_ambiente_do_host(),
        host=socket.gethostname(),
        razao=razao,
        prazo=prazo,
        sessao=identificador,
    )
    gravar = gravar_pelo_psql(
        config.get("KAMBA_BREAKGLASS_CONTENTOR", ""),
        config.get("KAMBA_DB_NAME", ""),
        config.get("KAMBA_SECRET_DB_BREAKGLASS_PASSWORD", ""),
    )
    terminal = os.environ.get("TERM", "dumb")
    return sessao(pedido, gravar, _abridor_de_shell(identificador, terminal))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(principal(sys.argv[1:]))
