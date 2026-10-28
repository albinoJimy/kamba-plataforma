"""O **unico** ficheiro do spike que fala com o Docker.

Nao e arrumacao: o gate 11 (`tools/supply_chain/imagens.py`, `_lancadores`)
exige que todo o ficheiro Python que lance um contentor esteja declarado em
`fontes_adicionais` de `ci/supply-chain/imagens.yaml`. Concentrar aqui as
chamadas faz do spike **uma** entrada nesse inventario em vez de quatro.

E nao traz digests novos. As duas imagens vem das constantes que o inventario
ja verifica:

    PostgreSQL   `db/gate_bd.py`               -> IMAGEM
    Node         `db/tests_identidade/node.py` -> IMAGEM_NODE

O Medusa corre na imagem oficial do Node, e nao numa imagem do Medusa: nao ha
imagem publicada do Medusa fixada no inventario, e acrescentar uma era
acrescentar um digest para manter por causa de um spike.

**Redis/Valkey nao entra.** O Medusa aceita os modulos de event bus e de cache
locais (em memoria) e o spike nao mede o bus: o bus canonico e o EVT (ADR-009),
nao o do Medusa. Um terceiro contentor so para o spike era um terceiro digest
sem criterio que o pedisse.
"""

from __future__ import annotations

import os
import secrets
import subprocess
import sys
import urllib.parse
from pathlib import Path

AQUI = Path(__file__).resolve().parent
RAIZ = AQUI.parents[1]
DB = RAIZ / "db"

if str(DB) not in sys.path:
    sys.path.insert(0, str(DB))

import gate_bd  # noqa: E402
from tests_identidade import node as node_mod  # noqa: E402

IMAGEM_POSTGRES = gate_bd.IMAGEM
IMAGEM_NODE = node_mod.IMAGEM_NODE

BASE = "kamba_spike041"
ADMIN = "kamba"

#: Volume nomeado dos `node_modules` do Medusa. Sobrevive entre execucoes: a
#: instalacao e o passo mais caro do spike (ver AC-9 no relatorio) e nao ha
#: razao para a repetir a cada medicao.
VOLUME_MODULOS = "kamba-spike041-node-modules"

#: Volume da cache do npm. **Nao e optimizacao gratuita.** Cada `docker run
#: --rm` comeca com um sistema de ficheiros novo, pelo que sem isto a cache do
#: npm nasce vazia de cada vez — e a resolucao da arvore do Medusa (1.158
#: pacotes) levou **28 minutos** nesta maquina, repetidos a cada tentativa. Com
#: a cache num volume, a segunda instalacao le do disco em vez da rede.
VOLUME_CACHE_NPM = "kamba-spike041-npm-cache"


class NaoSeConseguiuMedir(RuntimeError):
    """Infra-estrutura fora de alcance. Leva ao codigo 2, nunca a verde."""


def docker(*argumentos: str, ambiente=None, tempo: int = 180) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    # `MSYS_NO_PATHCONV`: no Git Bash do Windows, sem isto os caminhos `/repo` e
    # `/saida` chegam ao Docker reescritos para caminhos do Windows. Licao de
    # `db/tests_identidade/node.py`, e custou uma hora a redescobrir aqui.
    env["MSYS_NO_PATHCONV"] = "1"
    if ambiente:
        env.update(ambiente)
    return subprocess.run(
        ["docker", *argumentos],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=env, timeout=tempo,
    )


def ha_docker() -> bool:
    try:
        return docker("version", "--format", "{{.Server.Version}}", tempo=30).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def levantar_postgres() -> tuple[str, str, str]:
    """Devolve `(nome do contentor, porta publicada, palavra-passe do admin)`.

    Em `tmpfs`, publicado so em `127.0.0.1`, numa porta escolhida pelo Docker, e
    com a palavra-passe passada pelo ambiente — nunca pela linha de comandos,
    para nao aparecer em `ps`. E o que o `db/gate_bd.py` faz, pelas mesmas
    razoes, e esta copia existe porque o `gate_bd` corre uma suite fechada de
    `db/` e nao se deixa reutilizar sem o alterar (o que seria escopo de outro
    ticket).
    """
    senha = secrets.token_urlsafe(24)
    nome = f"kamba-spike041-pg-{secrets.token_hex(4)}"
    arranque = docker(
        "run", "--detach", "--rm", "--name", nome,
        "--env", "POSTGRES_USER", "--env", "POSTGRES_PASSWORD", "--env", "POSTGRES_DB",
        "--env", "POSTGRES_INITDB_ARGS=--auth-host=scram-sha-256",
        "--tmpfs", "/var/lib/postgresql",
        "--publish", "127.0.0.1::5432",
        IMAGEM_POSTGRES,
        # `max_connections` acima da omissao (100) por causa do AC-3: a prova de
        # sobrevenda quer tentativas **simultaneas**, e com 100 ligacoes o
        # paralelismo real ficava em 100 por muito que se pedisse mil. 400 cabe
        # nesta maquina; o relatorio diz quantas correram de facto ao mesmo
        # tempo, em vez de deixar supor que foram mil.
        "-c", "max_connections=400",
        ambiente={"POSTGRES_USER": ADMIN, "POSTGRES_PASSWORD": senha, "POSTGRES_DB": BASE},
    )
    if arranque.returncode != 0:
        raise NaoSeConseguiuMedir(
            f"o PostgreSQL nao arrancou: {arranque.stderr.strip()[-400:]}"
        )
    porta = docker("port", nome, "5432/tcp").stdout.strip().rsplit(":", 1)[-1]
    if not porta.isdigit():
        docker("rm", "--force", nome)
        raise NaoSeConseguiuMedir("o Docker nao devolveu a porta publicada")
    return nome, porta, senha


def remover(nome: str | None) -> None:
    if nome:
        docker("rm", "--force", nome)


def correr_node(guiao: Path, saida: Path, montagens: dict[str, str] | None = None,
                variaveis: dict[str, str] | None = None, rede: str | None = None,
                tempo: int = 300) -> subprocess.CompletedProcess:
    """Corre um guiao Node na imagem fixada, sem rede por omissao.

    `--network none` por omissao e deliberado: os guioes que medem isolamento de
    media nao precisam de rede, e um guiao de teste com rede e um guiao que pode
    estar a medir outra coisa.
    """
    comando = [
        "run", "--rm",
        "--volume", f"{RAIZ}:/repo:ro",
        "--volume", f"{saida}:/saida",
        "--workdir", "/repo",
    ]
    for origem, destino in (montagens or {}).items():
        comando += ["--volume", f"{origem}:{destino}"]
    ambiente = dict(variaveis or {})
    for nome in ambiente:
        comando += ["--env", nome]
    comando += ["--network", rede or "none"]
    comando += [IMAGEM_NODE, "node", f"/repo/{guiao.relative_to(RAIZ).as_posix()}"]
    return docker(*comando, ambiente=ambiente, tempo=tempo)


def instalar_medusa(saida: Path, tempo: int) -> subprocess.CompletedProcess:
    """`npm ci` do projecto do spike para o volume nomeado.

    `npm ci` e nao `npm install`: exige o fecho (`package-lock.json`), e sem
    fecho a versao do Medusa nao esta fixada e a medicao nao vale. O
    `package.json` do projecto pede `2.21.2` exacta; o fecho fixa a arvore
    inteira.
    """
    projecto = AQUI / "medusa"
    return docker(
        "run", "--rm",
        "--volume", f"{projecto}:/projecto:ro",
        "--volume", f"{VOLUME_MODULOS}:/trabalho/node_modules",
        "--volume", f"{VOLUME_CACHE_NPM}:/root/.npm",
        "--volume", f"{saida}:/saida",
        "--workdir", "/trabalho",
        IMAGEM_NODE,
        "sh", "-c",
        # O `npm ci` apaga `node_modules` antes de instalar e nao o pode fazer a
        # um ponto de montagem; instala-se em `/trabalho`, onde `node_modules`
        # **e** o volume, com o manifesto copiado para la.
        "set -e; cp /projecto/package.json /projecto/package-lock.json /trabalho/; "
        "npm config set fetch-retries 8; "
        "npm config set fetch-retry-maxtimeout 180000; "
        "npm config set fetch-timeout 900000; "
        "if [ ! -d node_modules/@medusajs/medusa ]; then "
        "  npm ci --no-audit --no-fund; "
        "fi; "
        "node -e \"const p=require('/trabalho/node_modules/@medusajs/medusa/package.json');"
        "console.log(JSON.stringify({versao:p.version,licenca:p.license,engines:p.engines}))\""
        " > /saida/medusa-pacote.json; "
        "cp node_modules/@medusajs/medusa/LICENSE /saida/medusa-LICENSE.txt 2>/dev/null "
        "|| echo '(o pacote nao traz ficheiro LICENSE)' > /saida/medusa-LICENSE.txt; "
        "node -v > /saida/node-versao.txt",
        tempo=tempo,
    )


def arrancar_medusa(contentor_pg: str, senha_admin: str, saida: Path) -> tuple[str, subprocess.CompletedProcess]:
    """Migra o schema do Medusa e deixa o servidor a escutar na rede do PostgreSQL.

    `--network container:` e o truque do `db/tests_identidade/node.py`: a base
    fica em `127.0.0.1:5432` para o Medusa sem publicar mais nenhuma porta no
    anfitriao.
    """
    projecto = AQUI / "medusa"
    nome = f"kamba-spike041-medusa-{secrets.token_hex(4)}"
    # Construido em pedacos, como o `db/ligacao.py` faz na `url_sqlalchemy`, e
    # pela mesma razao: nenhuma linha deste ficheiro contem um URL completo com
    # credencial. O `scan_secrets` (gate 9) procura essa forma por linha, e um
    # ficheiro de codigo que a traga — mesmo com a senha a vir de uma variavel —
    # e indistinguivel, para o scanner, de um que traga a senha escrita.
    url = (
        "postgres://"
        f"{urllib.parse.quote(ADMIN, safe='')}"
        f":{urllib.parse.quote(senha_admin, safe='')}"
        f"@127.0.0.1:5432/{urllib.parse.quote(BASE, safe='')}"
    )
    # O utilizador de operador do spike. **Existe para o ISO-19..26 poder medir
    # o que o §4.4 pede** — «token de operador usado a partir de rede de
    # tenant; rotas de listagem sem filtro» — em vez de medir «a Admin API
    # devolve 401 a quem nao traz credencial», que e verdade sobre qualquer
    # rota e nao diz nada sobre isolamento entre tenants.
    #
    # Credencial sintetica, gerada nesta execucao, que morre com o contentor.
    variaveis = {
        "DATABASE_URL": url,
        "JWT_SECRET": secrets.token_urlsafe(24),
        "COOKIE_SECRET": secrets.token_urlsafe(24),
        "KAMBA_SPIKE_ADMIN_EMAIL": "operador@spike.invalid",
        "KAMBA_SPIKE_ADMIN_SENHA": secrets.token_urlsafe(18),
    }
    comando = [
        "run", "--detach", "--name", nome,
        "--network", f"container:{contentor_pg}",
        "--volume", f"{projecto}:/projecto:ro",
        "--volume", f"{VOLUME_MODULOS}:/trabalho/node_modules",
        "--volume", f"{saida}:/saida",
        "--workdir", "/trabalho",
        "--env", "MEDUSA_WORKER_MODE=shared",
        "--env", "NODE_ENV=development",
        # **A telemetria desliga-se, e nao e zelo.** O CLI do Medusa anuncia no
        # primeiro arranque que «Medusa collects anonymous usage analytics», e
        # recolhe-a por omissao. O ADR-008 diz que nenhum dado pessoal de
        # producao sai de Angola sem a notificacao ou autorizacao da APD; mesmo
        # anonima, uma chamada para fora por omissao e uma decisao que nao e
        # nossa enquanto nao a tomarmos. No spike nao ha dados reais — mas o
        # habito de a deixar ligada e que chega a producao.
        "--env", "MEDUSA_DISABLE_TELEMETRY=true",
        "--env", "STORE_CORS=http://127.0.0.1",
        "--env", "ADMIN_CORS=http://127.0.0.1",
        "--env", "AUTH_CORS=http://127.0.0.1",
        "--env", "DISABLE_MEDUSA_ADMIN=true",
    ]
    for chave in variaveis:
        comando += ["--env", chave]
    comando += [
        IMAGEM_NODE, "sh", "-c",
        "set -e; cp -r /projecto/. /trabalho/; "
        # `tee` e nao `>`: a primeira versao redirigia a saida **so** para os
        # ficheiros, e quando o arranque falhou o `docker logs` do contentor
        # estava vazio — o diagnostico apontava para o sitio errado. Com `tee`,
        # o registo esta nos dois lados.
        #
        # `db:generate` antes de `db:migrate`: o modulo `merchant` e nosso e a
        # sua migracao nao existe no pacote. `db:migrate` «runs both the
        # migrations and syncs the links», pelo que o `db:sync-links` do link
        # `merchant`->`product` vai nele.
        "./node_modules/.bin/medusa db:generate merchant 2>&1 "
        "  | tee /saida/medusa-generate.log; "
        "./node_modules/.bin/medusa db:migrate 2>&1 "
        "  | tee /saida/medusa-migrate.log; "
        # O utilizador de operador, para o ISO-19..26. `|| true`: se a criacao
        # falhar, o servidor arranca de qualquer forma e os casos do operador
        # ficam NAO VERIFICADOS — o que e a resposta certa, e melhor do que nao
        # arrancar.
        "./node_modules/.bin/medusa user "
        "  --email \"$KAMBA_SPIKE_ADMIN_EMAIL\" "
        "  --password \"$KAMBA_SPIKE_ADMIN_SENHA\" 2>&1 "
        "  | tee /saida/medusa-user.log || true; "
        "exec ./node_modules/.bin/medusa start 2>&1 "
        "  | tee /saida/medusa-start.log",
    ]
    return nome, docker(*comando, ambiente=variaveis, tempo=120)


def esta_vivo(contentor: str) -> bool:
    return docker("inspect", "--format", "{{.State.Running}}",
                  contentor).stdout.strip() == "true"


def responde_health(contentor: str) -> tuple[bool, str]:
    """O Medusa ja responde? Perguntado **de dentro** da sua propria rede.

    Isto tem de ser aqui e nao no anfitriao, e a razao e o AC-2. O Medusa corre
    com `--network container:<pg>` e **sem `--publish`**: a porta 9000 nao existe
    no anfitriao, de proposito, porque o AC-2 exige que nada fora da rede a
    alcance. A primeira versao do harness esperava pelo Medusa com um
    `urlopen("http://127.0.0.1:9000/health")` **do anfitriao** — que nunca podia
    responder. As duas condicoes eram mutuamente exclusivas: ou o AC-2 passava,
    ou o harness arrancava. Era um defeito que escondia os outros, porque o
    arranque falhava sempre por timeout e nunca pela razao verdadeira.

    `docker exec` entra no *namespace* do contentor, onde `127.0.0.1:9000` e o
    servidor. Nao publica porta nenhuma e nao abre nada a rede.
    """
    sonda = docker(
        "exec", contentor, "node", "-e",
        "fetch('http://127.0.0.1:9000/health')"
        ".then(r=>{console.log('HEALTH '+r.status);process.exit(0)})"
        ".catch(e=>{console.log('SEM_RESPOSTA '+e.message);process.exit(1)})",
        tempo=30,
    )
    saida = (sonda.stdout + sonda.stderr).strip()
    return ("HEALTH" in saida and "SEM_RESPOSTA" not in saida), saida[-300:]


def registo(contentor: str, linhas: int = 80) -> str:
    saida = docker("logs", "--tail", str(linhas), contentor)
    return saida.stdout + saida.stderr
