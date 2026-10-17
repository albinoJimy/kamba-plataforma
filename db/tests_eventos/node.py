"""Como correr o publicador — que e Node — a partir da suite (KAM-005).

O padrao e o de `db/tests_identidade/node.py`, com uma diferenca que vem do
criterio 5: aqui ha **processos** a arrancar, a morrer e a disputar a
lideranca, e nao uma suite de testes a correr de uma vez. Por isso o que isto
devolve e um `Popen`, com `parar()` e `matar()`, e nao um resultado.

Onde corre: com `node` no `PATH` (o CI tem-no; a accao `preparar` instala-o),
no proprio *runner*, e chega a base e a fila pelas portas publicadas em
`127.0.0.1`. Sem `node` — o caso de uma maquina de desenvolvimento em Windows —
corre-se a imagem oficial **na rede do gate**, e ai a base e a fila tem-se pelo
**nome do contentor**, nao pela porta publicada.

O nome da rede e dos contentores chegam em `KAMBA_GATE_REDE`,
`KAMBA_DB_HOST_NA_REDE` e `KAMBA_GATE_FILA`, postos por `db/gate_bd.py`. Sem
eles a suite **falha** em vez de saltar: num gate, saltar e falhar.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
PACOTE = RAIZ / "packages" / "core-ts"

#: A mesma imagem e o mesmo digest de `db/tests_identidade/node.py`, pela mesma
#: razao: e a versao de `.node-version`, e `ci/supply-chain/imagens.yaml`
#: declara-a. Nao se reimporta de la para que o gate 11 encontre a constante
#: neste ficheiro tambem — o inventario e por ficheiro, nao por valor.
IMAGEM_NODE = (
    "node:24.21.0-trixie-slim"
    "@sha256:173f125896c3b47ddf056734c7ea789d04595a6a08769a8f78e0df642781fb66"
)

VARIAVEL_DA_REDE = "KAMBA_GATE_REDE"
VARIAVEL_DO_ANFITRIAO = "KAMBA_DB_HOST_NA_REDE"
VARIAVEL_DA_FILA = "KAMBA_GATE_FILA"
VARIAVEL_DOS_MODULOS = "KAMBA_RAIZ_NODE_MODULES"


class SemAmbienteDoGate(RuntimeError):
    """Falta o que `db/gate_bd.py` define."""


def _exigir(nome: str) -> str:
    valor = os.environ.get(nome, "")
    if not valor:
        raise SemAmbienteDoGate(
            f"{nome} nao esta definida. A suite de eventos corre o publicador "
            "contra a base e a fila do gate; `python db/gate_bd.py --suite "
            "tests_eventos` levanta-as e define-a."
        )
    return valor


def _raiz_dos_modulos() -> Path:
    return Path(os.environ.get(VARIAVEL_DOS_MODULOS) or RAIZ)


def _ligar_modulos() -> None:
    origem = _raiz_dos_modulos()
    if origem == RAIZ:
        return
    for relativo in ("node_modules", "packages/core-ts/node_modules"):
        destino = RAIZ / relativo
        if not destino.exists():
            destino.symlink_to(origem / relativo, target_is_directory=True)


#: Papel e variavel da palavra-passe de cada identidade que os programas da
#: suite usam. Os nomes sao os do `db/ligacao.py`; repetem-se aqui e nao se
#: importam porque o `ligacao` fala com o `pg8000` e isto constroi uma URL para
#: o `pg` do Node — o que e comum e o nome do segredo, nao o codigo.
PAPEIS = {
    "batch": ("kamba_batch", "KAMBA_SECRET_DB_BATCH_PASSWORD"),
    "app": ("kamba_app", "KAMBA_SECRET_DB_APP_PASSWORD"),
}


def url_da_base(na_rede: bool, papel: str = "batch") -> str:
    """`postgres://...` para um programa da suite, com o papel que ele usa.

    `batch` e a omissao porque e o do publicador (`BYPASSRLS`, le o outbox de
    todos os tenants). O **consumidor** corre como `app`: tem `INSERT` em
    `events_consumed` e na DLQ, esta sujeito a RLS e ve so o tenant do evento
    que tem em mao. Correr o consumidor como `batch` nao falhava por RLS —
    falhava por privilegio, porque `kamba_batch` nao tem `INSERT` nestas
    tabelas, e foi assim que o defeito apareceu.
    """
    try:
        nome, variavel = PAPEIS[papel]
    except KeyError:
        raise ValueError(f"papel desconhecido para a URL da base: {papel!r}") from None
    senha = os.environ[variavel]
    if na_rede:
        anfitriao, porta = _exigir(VARIAVEL_DO_ANFITRIAO), "5432"
    else:
        anfitriao = os.environ.get("KAMBA_DB_HOST", "127.0.0.1")
        porta = os.environ.get("KAMBA_DB_PORT", "5432")
    base = os.environ["KAMBA_DB_NAME"]
    # A palavra-passe vai na URL porque e assim que o `pg` a aceita; a URL passa
    # pelo **ambiente** do processo, nunca pela linha de comandos.
    return f"postgres://{nome}:{senha}@{anfitriao}:{porta}/{base}"


def url_da_fila(na_rede: bool) -> str:
    if na_rede:
        return f"redis://{_exigir(VARIAVEL_DA_FILA)}:6379"
    anfitriao = os.environ.get("KAMBA_FILA_HOST", "127.0.0.1")
    porta = os.environ["KAMBA_FILA_PORT"]
    return f"redis://{anfitriao}:{porta}"


class Processo:
    """Um publicador a correr, o que ele escreveu, e as duas formas de o terminar.

    O que ele escreve vai para um **ficheiro**, e nao para um `PIPE`. Duas
    razoes, e as duas foram medidas: um `PIPE` que ninguem le enche-se e o
    processo bloqueia a escrever, e um `PIPE` so se le depois de o processo
    terminar — o que deixava a suite a afirmar «nao recuou» sem poder dizer
    porque. Com ficheiro, `linhas()` responde a qualquer momento, incluindo com
    o processo vivo, e e isso que faz as mensagens de falha dizerem algo.

    `matar()` e `kill -9` **de verdade**, e e o criterio 3 que o pede. Num
    contentor, matar o `Popen` mata o `docker run` e nao o Node de dentro — e o
    Node de dentro ficava a publicar depois de o teste o dar por morto, com o
    *lock* consultivo na mao. Por isso, quando corre em contentor, o sinal vai
    ao contentor (`docker kill --signal KILL`).
    """

    def __init__(
        self,
        popen: subprocess.Popen,
        contentor: str | None,
        registo: Path,
        aberto=None,
    ) -> None:
        self.popen = popen
        self.contentor = contentor
        self.registo = registo
        # O descritor para onde o processo escreve. Fecha-se quando ele morre:
        # em Windows, um ficheiro com um descritor aberto nao se apaga, e a
        # limpeza do directorio temporario falhava com `WinError 32` (medido).
        self._aberto = aberto

    def vivo(self) -> bool:
        return self.popen.poll() is None

    @property
    def jsonl(self) -> Path:
        """O ficheiro das linhas JSON. O `stdout` do processo vai para outro.

        Sao dois porque o `log-lint` do gate 2 proibe escrita directa no
        `stdout`: o publicador escreve as suas linhas num ficheiro proprio, e o
        `.log` fica com o que o Node escreve por sua conta (erros, pilhas).
        """
        return self.registo.with_suffix(".jsonl")

    def texto(self) -> str:
        """Tudo o que escreveu ate agora, dos dois ficheiros. Com o processo vivo."""
        partes = []
        for caminho in (self.jsonl, self.registo):
            try:
                partes.append(caminho.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                pass
        return "".join(partes)

    def linhas(self) -> list[dict]:
        """As linhas JSON que escreveu. As outras (erros do Node) ficam de fora."""
        import json as _json

        encontradas = []
        for linha in self.texto().splitlines():
            try:
                dados = _json.loads(linha)
            except ValueError:
                continue
            if isinstance(dados, dict):
                encontradas.append(dados)
        return encontradas

    def diagnostico(self, limite: int = 2000) -> str:
        """O fim do registo, para entrar numa mensagem de falha."""
        texto = self.texto()
        corte = texto[-limite:]
        estado = "vivo" if self.vivo() else f"morto ({self.popen.poll()})"
        return f"\n--- publicador {self.registo.stem} ({estado}) ---\n{corte}\n---"

    def _fechar(self) -> None:
        if self._aberto is not None:
            try:
                self._aberto.close()
            except OSError:
                pass
            self._aberto = None

    def matar(self) -> None:
        if self.contentor is not None:
            subprocess.run(
                ["docker", "kill", "--signal", "KILL", self.contentor],
                capture_output=True,
            )
        self.popen.kill()
        try:
            self.popen.wait(timeout=60)
        except subprocess.TimeoutExpired:
            pass
        self._fechar()

    def parar(self) -> str:
        """`SIGTERM`: encerramento limpo, que larga o *lock*."""
        if self.contentor is not None:
            subprocess.run(
                ["docker", "kill", "--signal", "TERM", self.contentor],
                capture_output=True,
            )
        else:
            self.popen.terminate()
        try:
            self.popen.wait(timeout=60)
        except subprocess.TimeoutExpired:
            self.matar()
        texto = self.texto()
        self._fechar()
        return texto


#: Onde a pasta dos registos entra no contentor. Nao e o caminho do anfitriao:
#: um `C:\...` do lado de dentro e lido pelo Docker como `src:dst:mode` e a
#: unidade do destino passa a ser o `dst`.
PASTA_DOS_REGISTOS = "/registos"


def lancar(
    argumentos: list[str],
    extra: dict[str, str] | None = None,
    rotulo: str = "pub",
    registo: Path | None = None,
    variavel_do_registo: str = "KAMBA_PUB_REGISTO",
) -> Processo:
    """Lanca `node <argumentos>` em `packages/core-ts`. Nao espera por ele.

    `registo` e o ficheiro para onde vai tudo o que ele escreve. Sem ele,
    escreve-se ao lado da raiz dos modulos, num nome com o rotulo.

    `variavel_do_registo` e o nome da variavel em que o programa espera esse
    caminho. Cada programa tem a sua (`KAMBA_PUB_REGISTO`,
    `KAMBA_CON_REGISTO`, `KAMBA_RECON_REGISTO`), e passar a do publicador a um
    consumidor deixava-o **mudo**: a suite esperava por uma linha «arrancou»
    que nunca era escrita, e a falha lia-se «o consumidor nao arrancou».
    """
    import secrets
    import tempfile

    if registo is None:
        registo = Path(tempfile.gettempdir()) / f"kamba-{rotulo}-{secrets.token_hex(3)}.log"
    na_rede = shutil.which("node") is None
    ambiente = dict(os.environ)
    ambiente.update(
        {
            "KAMBA_PUBLICADOR_DB_URL": url_da_base(na_rede),
            "KAMBA_QUEUE_URL": url_da_fila(na_rede),
        }
    )
    # O ficheiro de linhas de registo. Dentro do contentor a pasta entra num
    # caminho **POSIX** fixo: um caminho do Windows do lado de dentro fazia o
    # Docker ler o `C:` do destino como o segundo campo do `--volume` e recusar
    # («invalid mode: /Users/...», medido neste anfitriao). O teste le o
    # ficheiro pelo caminho do anfitriao; o processo escreve-o pelo de dentro.
    linhas = registo.with_suffix(".jsonl")
    ambiente[variavel_do_registo] = (
        f"{PASTA_DOS_REGISTOS}/{linhas.name}" if na_rede else str(linhas)
    )
    ambiente.update(extra or {})
    aberto = registo.open("w", encoding="utf-8", errors="replace", newline="\n")
    if not na_rede:
        _ligar_modulos()
        return Processo(
            subprocess.Popen(
                ["node", *argumentos],
                cwd=PACOTE,
                env=ambiente,
                stdout=aberto,
                stderr=subprocess.STDOUT,
            ),
            None,
            registo,
            aberto,
        )

    contentor = f"kamba-{rotulo}-{secrets.token_hex(3)}"
    comando = [
        "docker", "run", "--rm", "--name", contentor,
        "--network", _exigir(VARIAVEL_DA_REDE),
        "--volume", f"{RAIZ}:/repo:ro",
        "--workdir", "/repo/packages/core-ts",
    ]
    modulos = _raiz_dos_modulos()
    if modulos != RAIZ:
        for relativo in ("node_modules", "packages/core-ts/node_modules"):
            (RAIZ / relativo).mkdir(parents=True, exist_ok=True)
            comando += ["--volume", f"{modulos / relativo}:/repo/{relativo}:ro"]
    for nome in (
        "KAMBA_PUBLICADOR_DB_URL",
        "KAMBA_QUEUE_URL",
        variavel_do_registo,
        *(extra or {}),
    ):
        comando += ["--env", nome]
    comando += ["--volume", f"{registo.parent}:{PASTA_DOS_REGISTOS}"]
    comando += [IMAGEM_NODE, "node", *argumentos]
    # `MSYS_NO_PATHCONV`: no Git Bash do Windows, sem isto, `/repo` era
    # reescrito para um caminho do Windows antes de chegar ao Docker.
    ambiente["MSYS_NO_PATHCONV"] = "1"
    return Processo(
        subprocess.Popen(
            comando,
            env=ambiente,
            stdout=aberto,
            stderr=subprocess.STDOUT,
        ),
        contentor,
        registo,
        aberto,
    )
