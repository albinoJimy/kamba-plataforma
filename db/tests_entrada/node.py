"""Como correr o GWY e o *worker* de entrada — que sao Node — a partir da suite.

O padrao e o de `db/tests_eventos/node.py`, com **uma diferenca que importa**:
ali lanca-se um programa de ensaio escrito para a suite (`publicador_runner.ts`),
e aqui lancam-se os **processos de producao** — `services/gwy/src/server.ts` e
`services/worker-canal/src/entrada.ts`, sem uma linha de codigo de teste pelo
meio. A razao e o que o KAM-013 tem de provar: «o 200 so e devolvido depois de o
*job* estar enfileirado» e «com Redis indisponivel o GWY responde 503 e nunca
200» sao propriedades do servidor HTTP a falar com uma fila a serio, e um
programa de ensaio que as imitasse provava-se a si proprio.

Por isso a suite tem de saber lancar dois servicos em pastas diferentes, e e a
unica diferenca de forma face ao `tests_eventos`: o `cwd` e um argumento.

Onde corre: com `node` no `PATH` (o CI tem-no; a accao `preparar` instala-o).
Sem `node` — o caso de uma maquina de desenvolvimento em Windows — corre-se a
imagem oficial **na rede do gate**, e ai a base e a fila tem-se pelo **nome do
contentor**, nao pela porta publicada.
"""

from __future__ import annotations

import os
import secrets
import shutil
import subprocess
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]

#: A mesma imagem e o mesmo digest dos outros dois `node.py`, pela mesma razao:
#: e a versao de `.node-version`, e `ci/supply-chain/imagens.yaml` declara-a por
#: **ficheiro** — nao se reimporta de la para que o gate 11 encontre a constante
#: aqui tambem.
IMAGEM_NODE = (
    "node:24.21.0-trixie-slim"
    "@sha256:173f125896c3b47ddf056734c7ea789d04595a6a08769a8f78e0df642781fb66"
)

VARIAVEL_DA_REDE = "KAMBA_GATE_REDE"
VARIAVEL_DO_ANFITRIAO = "KAMBA_DB_HOST_NA_REDE"
VARIAVEL_DA_FILA = "KAMBA_GATE_FILA"
VARIAVEL_DOS_MODULOS = "KAMBA_RAIZ_NODE_MODULES"

#: Onde a pasta dos registos entra no contentor. Nao e o caminho do anfitriao:
#: um `C:\\...` do lado de dentro e lido pelo Docker como `src:dst:mode`.
PASTA_DOS_REGISTOS = "/registos"


class SemAmbienteDoGate(RuntimeError):
    """Falta o que `db/gate_bd.py` define."""


def _exigir(nome: str) -> str:
    valor = os.environ.get(nome, "")
    if not valor:
        raise SemAmbienteDoGate(
            f"{nome} nao esta definida. A suite de entrada corre o GWY e o worker "
            "contra a base e a fila do gate; `python db/gate_bd.py --suite "
            "tests_entrada` levanta-as e define-a."
        )
    return valor


def na_rede() -> bool:
    """Sem `node` no `PATH`, corre-se em contentor, na rede do gate."""
    return shutil.which("node") is None


def _raiz_dos_modulos() -> Path:
    return Path(os.environ.get(VARIAVEL_DOS_MODULOS) or RAIZ)


def _ligar_modulos(pastas: tuple[str, ...]) -> None:
    origem = _raiz_dos_modulos()
    if origem == RAIZ:
        return
    for relativo in pastas:
        destino = RAIZ / relativo
        if not destino.exists():
            destino.symlink_to(origem / relativo, target_is_directory=True)


def url_da_base(papel: str = "app") -> str:
    """`postgres://...` para um processo da suite.

    `app` e a omissao porque e o papel do *worker* de entrada: tem `SELECT` e
    `INSERT` em `inbound_events`, `INSERT` em `unrouted_events` e `UPDATE` so
    em `processado_at`. Corre-lo como `batch` nao falhava por RLS — estas duas
    tabelas nao tem — mas escondia exactamente o que esta suite tem de medir:
    que os privilegios da revisao `0008` bastam e nao sobram.
    """
    papeis = {
        "app": ("kamba_app", "KAMBA_SECRET_DB_APP_PASSWORD"),
        "batch": ("kamba_batch", "KAMBA_SECRET_DB_BATCH_PASSWORD"),
    }
    nome, variavel = papeis[papel]
    senha = os.environ[variavel]
    if na_rede():
        anfitriao, porta = _exigir(VARIAVEL_DO_ANFITRIAO), "5432"
    else:
        anfitriao = os.environ.get("KAMBA_DB_HOST", "127.0.0.1")
        porta = os.environ.get("KAMBA_DB_PORT", "5432")
    base = os.environ["KAMBA_DB_NAME"]
    # A palavra-passe vai na URL porque e assim que o `pg` a aceita; a URL passa
    # pelo **ambiente** do processo, nunca pela linha de comandos.
    return f"postgres://{nome}:{senha}@{anfitriao}:{porta}/{base}"


def url_da_fila() -> str:
    if na_rede():
        return f"redis://{_exigir(VARIAVEL_DA_FILA)}:6379"
    anfitriao = os.environ.get("KAMBA_FILA_HOST", "127.0.0.1")
    porta = os.environ["KAMBA_FILA_PORT"]
    return f"redis://{anfitriao}:{porta}"


class Processo:
    """Um servico a correr, o que ele escreveu, e as duas formas de o terminar.

    O que ele escreve vai para um **ficheiro** e nao para um `PIPE`, pela mesma
    razao medida em `tests_eventos/node.py`: um `PIPE` que ninguem le enche-se e
    o processo bloqueia, e um `PIPE` so se le depois de o processo terminar — o
    que deixava a suite a afirmar «nao respondeu 503» sem poder dizer porque.
    """

    def __init__(
        self,
        popen: subprocess.Popen,
        contentor: str | None,
        registo: Path,
        aberto,
        porta: int | None = None,
    ) -> None:
        self.popen = popen
        self.contentor = contentor
        self.registo = registo
        self.porta = porta
        self._aberto = aberto

    def vivo(self) -> bool:
        return self.popen.poll() is None

    def texto(self) -> str:
        try:
            return self.registo.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    def linhas(self) -> list[dict]:
        """As linhas JSON do *logger*. As outras (erros do Node) ficam de fora."""
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
        estado = "vivo" if self.vivo() else f"morto ({self.popen.poll()})"
        return f"\n--- {self.registo.stem} ({estado}) ---\n{self.texto()[-limite:]}\n---"

    def _fechar(self) -> None:
        if self._aberto is not None:
            try:
                self._aberto.close()
            except OSError:
                pass
            self._aberto = None

    def parar(self) -> str:
        if self.contentor is not None:
            subprocess.run(
                ["docker", "kill", "--signal", "TERM", self.contentor], capture_output=True
            )
        else:
            self.popen.terminate()
        try:
            self.popen.wait(timeout=60)
        except subprocess.TimeoutExpired:
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
        texto = self.texto()
        self._fechar()
        return texto


def lancar(
    pasta: str,
    guiao: str,
    extra: dict[str, str],
    rotulo: str,
    porta: int | None = None,
) -> Processo:
    """Lanca `node <guiao>` em `pasta` (relativa a raiz). Nao espera por ele.

    `porta` e a porta que o processo publica, quando tem servidor HTTP. Em
    contentor, publica-se **so em 127.0.0.1**: um `-p 3000:3000` sem anfitriao
    abria a porta na rede local da maquina de quem corre o gate.
    """
    registo = Path(tempfile.gettempdir()) / f"kamba-{rotulo}-{secrets.token_hex(3)}.log"
    ambiente = dict(os.environ)
    ambiente.update(extra)
    aberto = registo.open("w", encoding="utf-8", errors="replace", newline="\n")

    if not na_rede():
        _ligar_modulos(("node_modules", f"{pasta}/node_modules"))
        return Processo(
            subprocess.Popen(
                ["node", guiao],
                cwd=RAIZ / pasta,
                env=ambiente,
                stdout=aberto,
                stderr=subprocess.STDOUT,
            ),
            None,
            registo,
            aberto,
            porta,
        )

    contentor = f"kamba-{rotulo}-{secrets.token_hex(3)}"
    comando = [
        "docker", "run", "--rm", "--name", contentor,
        "--network", _exigir(VARIAVEL_DA_REDE),
        "--volume", f"{RAIZ}:/repo:ro",
        "--volume", f"{registo.parent}:{PASTA_DOS_REGISTOS}",
        "--workdir", f"/repo/{pasta}",
    ]
    modulos = _raiz_dos_modulos()
    if modulos != RAIZ:
        for relativo in ("node_modules", f"{pasta}/node_modules"):
            comando += ["--volume", f"{modulos / relativo}:/repo/{relativo}:ro"]
    if porta is not None:
        # So em `127.0.0.1`: o gate nao abre portas na rede de quem o corre.
        comando += ["--publish", f"127.0.0.1:{porta}:{porta}"]
        ambiente["HOST"] = "0.0.0.0"
    # **As variaveis de `extra` passam todas, uma a uma, e nao por prefixo.**
    # Isto foi um defeito medido: o filtro era
    # `nome.startswith(("KAMBA_", "PORT", "HOST", "NODE_"))`, e o
    # `ENTRADA_PORT` do *worker* nao casa nenhum deles — o processo arrancava,
    # escutava na porta por omissao (3013) e a porta publicada apontava para
    # outra. Doze testes falharam com «o worker de entrada nao arrancou»
    # enquanto o registo dele dizia `service_started`. O GWY passava porque usa
    # `PORT`, que casava o filtro por acidente.
    #
    # As do ambiente geral continuam por prefixo: sao as que `gate_bd.py` poe
    # (`KAMBA_*`) e as que o Node le por si (`NODE_*`).
    nomes = set(extra) | {
        nome
        for nome in ambiente
        if nome.startswith(("KAMBA_", "NODE_")) or nome in ("PORT", "HOST")
    }
    for nome in sorted(nomes):
        valor = ambiente.get(nome)
        if valor is not None:
            comando += ["--env", f"{nome}={valor}"]
    comando += [IMAGEM_NODE, "node", guiao]
    return Processo(
        subprocess.Popen(
            comando, env=ambiente, stdout=aberto, stderr=subprocess.STDOUT
        ),
        contentor,
        registo,
        aberto,
        porta,
    )
