"""A fila descartavel das suites de eventos (KAM-005).

Esta num ficheiro proprio, e nao em `db/gate_bd.py`, por uma razao mecanica: o
`ci/supply-chain/imagens.yaml` aceita **uma** constante por ficheiro em
`fontes_adicionais`, e o `gate_bd.py` ja la esta com a `IMAGEM` do PostgreSQL.
Duas entradas para o mesmo ficheiro sao recusadas («ficheiro repetido»), e a
regra e boa: uma constante por ficheiro e o que torna a verificacao do digest
inequivoca. Logo, o digest da fila vive aqui.

So as suites `tests_eventos` e `tests_eventos_carga` a levantam: o publicador
precisa de um Redis-compativel real, e as garantias do BullMQ estao
**NAO VERIFICADO** (`docs/tecnica/evidencia/E4` §2.10) — provar o recuo, a
republicacao depois de um `kill -9` e a eleicao de lider contra uma fila em
memoria nao provava nada sobre elas.
"""

from __future__ import annotations

import socket
import subprocess

#: A fila do compose de desenvolvimento, com o mesmo digest. Declarada em
#: `ci/supply-chain/imagens.yaml` (`fontes_adicionais`): `make supply-chain`
#: falha se o digest daqui deixar de ser o do inventario. A imagem e a omissao
#: da decisao aberta D12 (Redis ou Valkey), nao uma escolha deste ticket.
IMAGEM = (
    "valkey/valkey:9.1.2-trixie"
    "@sha256:418652cfb58ef879d4978c33553735d7147016032d5aefaa14c828e611eb9dfd"
)


def porta_livre() -> int:
    """Uma porta livre em `127.0.0.1`, escolhida por este processo.

    O contentor da base deixa o Docker escolher (`127.0.0.1::5432`), e para ele
    chega. A fila **nao** pode: o criterio 4 para-a e volta a arranca-la, e um
    `docker start` de um contentor com porta efemera recebe uma porta **nova** —
    a suite ficava a falar com a porta antiga e lia «ligacao recusada» em todos
    os testes seguintes (medido). Com a porta fixada a mapeacao sobrevive ao
    reinicio. A janela entre fechar o socket e o Docker ligar-se a porta e uma
    corrida teorica; na pratica o gate corre um contentor de cada vez.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as tomada:
        tomada.bind(("127.0.0.1", 0))
        return int(tomada.getsockname()[1])


def arrancar(rede: str, nome: str) -> str:
    """Levanta a fila na rede dada. Devolve a porta publicada.

    `--appendonly yes --appendfsync everysec` sao os do compose de
    desenvolvimento, e nao sao cosmetica: o desenho assume que a fila perde no
    maximo 1 s (`docs/tecnica/06` §6.2) e o criterio 4 para-a de proposito. Os
    dados ficam em `tmpfs`: nada toca no disco e nada sobrevive.

    **Sem `--rm`**, ao contrario do contentor da base, e nao por descuido: com
    `--rm`, o `docker stop` do criterio 4 **remove** o contentor e nao ha
    `start` depois. Quem o remove e o `finally` de quem chamou.
    """
    porta = porta_livre()
    arranque = subprocess.run(
        [
            "docker", "run", "--detach", "--name", nome,
            "--network", rede,
            "--tmpfs", "/data",
            "--publish", f"127.0.0.1:{porta}:6379",
            IMAGEM,
            "--appendonly", "yes", "--appendfsync", "everysec",
            "--dir", "/data", "--save", "",
        ],
        capture_output=True,
        text=True,
    )
    if arranque.returncode != 0:
        raise RuntimeError(f"nao foi possivel arrancar a fila:\n{arranque.stderr}")
    return str(porta)
