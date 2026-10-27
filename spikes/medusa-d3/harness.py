"""Harness do spike KAM-041 — levanta o que e preciso e mede os dez criterios.

    python spikes/medusa-d3/harness.py                 # tudo
    python spikes/medusa-d3/harness.py --sem-medusa    # so o que nao precisa do Medusa
    python spikes/medusa-d3/harness.py --saida <dir>   # onde ficam os resultados

**Isto nao e um gate.** O KAM-041 e um spike: o produto e medicao, e a medicao
vive em `docs/spikes/KAM-041-medusa.md`. Se a decisao D3 fechar na opcao B, a
suite ISO entra na *pipeline* pela mao do KAM-042 — e e la que ganha um alvo
`make ci-<n>`, nao aqui.

Codigos de saida, e a distincao que importa:

    0   todos os criterios bloqueantes medidos e verdes
    1   algum criterio bloqueante medido e **vermelho**
    2   **nao se conseguiu medir** (Docker fora de alcance, Medusa nao arrancou,
        rede sem npm). Nao e verde, e o relatorio escreve NAO VERIFICADO.

O 2 e o codigo que este repositorio ja usa para «nao se conseguiu verificar»
(`db/gate_bd.py`). Um spike que confundisse «zero sobrevendas» com «o teste nao
chegou a correr» era pior do que nao ter spike: dava uma licenca de arquitectura
assinada por um teste que nunca concorreu.

O Docker vive todo em `contentor.py` — ver o cabecalho desse ficheiro para a
razao (gate 11) e para as imagens usadas.
"""

from __future__ import annotations

import argparse
import json
import secrets
import signal
import subprocess
import sys
import time
from pathlib import Path

AQUI = Path(__file__).resolve().parent
RAIZ = AQUI.parents[1]
DB = RAIZ / "db"

sys.path.insert(0, str(DB))
sys.path.insert(0, str(AQUI))

import bootstrap  # noqa: E402  (vem de `db/`, pelo sys.path acima)
import contentor  # noqa: E402
import ligacao  # noqa: E402
from contentor import NaoSeConseguiuMedir  # noqa: E402

ESPERA_DA_BASE = 90
#: Segundos para o `npm ci` do Medusa. Folga para uma rede lenta, nao alvo: o
#: tempo medido nesta maquina esta no relatorio.
TEMPO_DA_INSTALACAO = 2400
ESPERA_DO_MEDUSA = 300


def _esperar_pela_base(ambiente: dict[str, str]) -> None:
    """Tres ligacoes autenticadas seguidas.

    O `pg_isready` nao chega: o entrypoint da imagem arranca o servidor para o
    `initdb` e reinicia-o, e uma unica ligacao bem-sucedida pode ser ao
    primeiro.
    """
    limite = time.monotonic() + ESPERA_DA_BASE
    ultimo: Exception | None = None
    estaveis = 0
    while time.monotonic() < limite:
        try:
            ligacao.ligar("admin", ambiente).close()
            estaveis += 1
            if estaveis >= 3:
                return
        except Exception as erro:  # noqa: BLE001 — qualquer falha e «ainda nao»
            ultimo = erro
            estaveis = 0
        time.sleep(1)
    raise NaoSeConseguiuMedir(
        f"a base nao ficou disponivel em {ESPERA_DA_BASE}s: {type(ultimo).__name__}"
    )


def ambiente_da_base(porta: str, senha: str) -> dict[str, str]:
    import os

    ambiente = dict(os.environ)
    ambiente.update(
        {
            "KAMBA_DB_HOST": "127.0.0.1",
            "KAMBA_DB_PORT": porta,
            "KAMBA_DB_NAME": contentor.BASE,
            "POSTGRES_USER": contentor.ADMIN,
            "POSTGRES_PASSWORD": senha,
            "KAMBA_SECRET_DB_MIGRATOR_PASSWORD": secrets.token_urlsafe(24),
            "KAMBA_SECRET_DB_APP_PASSWORD": secrets.token_urlsafe(24),
            "KAMBA_SECRET_DB_BATCH_PASSWORD": secrets.token_urlsafe(24),
            "KAMBA_SECRET_DB_RESOLVER_PASSWORD": secrets.token_urlsafe(24),
            "KAMBA_SECRET_DB_IDENTITY_PASSWORD": secrets.token_urlsafe(24),
        }
    )
    return ambiente


def preparar_base(ambiente: dict[str, str]) -> None:
    """Papeis, revisoes 0001-0003 pelo Alembic, e o DDL do spike por cima.

    As revisoes correm pelo Alembic de verdade, nao por uma copia do DDL. E isso
    que torna o spike uma medicao da *pipeline* do §11 («Alembic, depois
    migracoes do Medusa») e nao de um esquema inventado para o teste.
    """
    import os

    anterior = dict(os.environ)
    os.environ.update(ambiente)
    try:
        bootstrap.aplicar()
        alembic = subprocess.run(
            [sys.executable, "-m", "alembic", "-c", "migrations/alembic.ini",
             "upgrade", "head"],
            cwd=DB, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=600,
        )
        if alembic.returncode != 0:
            raise NaoSeConseguiuMedir(
                f"alembic upgrade head falhou:\n{alembic.stdout}\n{alembic.stderr}"
            )
    finally:
        os.environ.clear()
        os.environ.update(anterior)

    extensoes = ambiente.get("KAMBA_SPIKE_EXTENSOES_PROPOSTAS") == "1"
    conexao = ligacao.ligar("migrator", ambiente)
    try:
        cursor = conexao.cursor()
        for ficheiro in ("01_encomendas.sql", "02_rls.sql", "03_grafo.sql",
                         "04_outbox.sql"):
            cursor.execute((AQUI / "ddl" / ficheiro).read_text(encoding="utf-8"))
        if extensoes:
            # §6.1: as duas transicoes «extensao proposta», so com a flag.
            cursor.execute(
                "INSERT INTO platform.order_state_graph (de, para) "
                "VALUES ('expirada','paga'), ('entregue','reembolso_pendente')"
            )
        conexao.commit()
    finally:
        conexao.close()


def preparar_medusa(contentor_pg: str, senha: str, saida: Path) -> tuple[str, dict]:
    """Instala, migra e arranca. Devolve `(contentor, metadados do pacote)`."""
    projecto = AQUI / "medusa"
    if not (projecto / "package-lock.json").is_file():
        raise NaoSeConseguiuMedir(
            "falta `spikes/medusa-d3/medusa/package-lock.json`. A instalacao e "
            "`npm ci`, que exige o fecho: sem ele a versao do Medusa nao esta "
            "fixada e a medicao nao vale. Ver o README do spike."
        )
    print("==> Medusa: instalacao (pode levar minutos na primeira vez)")
    inicio = time.monotonic()
    instalacao = contentor.instalar_medusa(saida, TEMPO_DA_INSTALACAO)
    duracao = time.monotonic() - inicio
    if instalacao.returncode != 0:
        (saida / "medusa-instalacao-falhou.log").write_text(
            instalacao.stdout + "\n" + instalacao.stderr, encoding="utf-8"
        )
        raise NaoSeConseguiuMedir(
            f"a instalacao do Medusa falhou ({instalacao.returncode}) em "
            f"{duracao:.0f}s; registo em {saida / 'medusa-instalacao-falhou.log'}"
        )
    pacote = json.loads((saida / "medusa-pacote.json").read_text(encoding="utf-8"))
    pacote["segundos_de_instalacao"] = round(duracao, 1)
    pacote["node"] = (saida / "node-versao.txt").read_text(encoding="utf-8").strip()
    print(f"    @medusajs/medusa {pacote['versao']}, licenca {pacote['licenca']!r}, "
          f"Node {pacote['node']} ({duracao:.0f}s)")

    print("==> Medusa: db:migrate e arranque")
    nome, arranque = contentor.arrancar_medusa(contentor_pg, senha, saida)
    if arranque.returncode != 0:
        raise NaoSeConseguiuMedir(
            f"o contentor do Medusa nao arrancou: {arranque.stderr.strip()[-400:]}"
        )
    _esperar_pelo_medusa(nome, saida)
    print("    o Medusa responde em /health (perguntado dentro da rede dele)")
    return nome, pacote


def _esperar_pelo_medusa(nome: str, saida: Path) -> None:
    """Espera que o Medusa responda, perguntando **de dentro da rede dele**.

    Ver `contentor.responde_health` para a razao: a porta 9000 nao esta
    publicada no anfitriao, e nao deve estar (AC-2).
    """
    def guardar_registo() -> Path:
        destino = saida / "medusa-arranque-falhou.log"
        partes = [contentor.registo(nome, 200)]
        # Os registos uteis estao nos ficheiros que o contentor escreve: o
        # `db:generate` e o `db:migrate` correm antes do servidor, e e neles que
        # um erro de configuracao aparece.
        for passo in ("medusa-generate.log", "medusa-migrate.log", "medusa-start.log"):
            caminho = saida / passo
            if caminho.is_file():
                partes.append(f"\n===== {passo} =====\n"
                              + caminho.read_text(encoding="utf-8", errors="replace"))
        destino.write_text("\n".join(partes), encoding="utf-8")
        return destino

    limite = time.monotonic() + ESPERA_DO_MEDUSA
    ultima = ""
    while time.monotonic() < limite:
        if not contentor.esta_vivo(nome):
            destino = guardar_registo()
            raise NaoSeConseguiuMedir(
                f"o Medusa morreu durante o arranque; registo em {destino}"
            )
        respondeu, ultima = contentor.responde_health(nome)
        if respondeu:
            return
        time.sleep(3)
    destino = guardar_registo()
    raise NaoSeConseguiuMedir(
        f"o Medusa nao respondeu em {ESPERA_DO_MEDUSA}s (ultima sonda: "
        f"{ultima}); registo em {destino}"
    )


def main(argv: list[str] | None = None) -> int:
    for sinal in (signal.SIGINT, signal.SIGTERM):
        signal.signal(
            sinal, lambda numero, _q: (_ for _ in ()).throw(SystemExit(128 + numero))
        )

    analisador = argparse.ArgumentParser(
        prog="harness", description=__doc__.split("\n")[0]
    )
    analisador.add_argument(
        "--sem-medusa", action="store_true",
        help="mede so o que nao depende do Medusa; os restantes criterios ficam "
             "NAO VERIFICADO (e nao verdes)",
    )
    analisador.add_argument(
        "--saida", type=Path, default=AQUI / "resultados",
        help="onde ficam os resultados e os registos",
    )
    argumentos = analisador.parse_args(argv)
    saida: Path = argumentos.saida.resolve()
    saida.mkdir(parents=True, exist_ok=True)

    import medir

    pg = medusa = None
    try:
        if not contentor.ha_docker():
            raise NaoSeConseguiuMedir(
                "o Docker nao responde. O spike levanta um PostgreSQL e corre o "
                "Medusa em contentores; nesta maquina nao ha `node` nem `pnpm` no "
                "PATH e nao se instala nada no anfitriao."
            )
        print("==> PostgreSQL descartavel")
        pg, porta, senha = contentor.levantar_postgres()
        ambiente = ambiente_da_base(porta, senha)
        _esperar_pela_base(ambiente)
        print("==> papeis, revisoes 0001-0003, DDL do spike")
        preparar_base(ambiente)

        pacote = None
        if not argumentos.sem_medusa:
            medusa, pacote = preparar_medusa(pg, senha, saida)

        return medir.correr(
            ambiente=ambiente, saida=saida, contentor_pg=pg,
            contentor_medusa=medusa, pacote_medusa=pacote,
        )
    except NaoSeConseguiuMedir as erro:
        print(f"\nNAO VERIFICADO: {erro}", file=sys.stderr)
        print(
            "    Codigo 2. Isto nao e um criterio verde nem um criterio "
            "vermelho: e a ausencia de medicao, e o relatorio escreve-o assim.",
            file=sys.stderr,
        )
        return 2
    finally:
        contentor.remover(medusa)
        contentor.remover(pg)


if __name__ == "__main__":
    sys.exit(main())
