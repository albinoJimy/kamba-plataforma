"""Cliente RESP minimo, para a suite perguntar a fila o que tem (KAM-005).

A suite precisa de responder a tres perguntas sobre a fila, e so a tres:

    quantos *jobs* distintos estao na fila X?
    um *job* com este `jobId` existe?
    a fila esta vazia?

Para isso nao se traz uma dependencia nova para `db/requirements/migrations.in`
— que e um ficheiro com *hashes* e um alvo `make lock` — nem se instala um
cliente Redis no *runner*. O protocolo RESP e de uma simplicidade que cabe aqui:
comandos em *arrays* de *bulk strings*, respostas com cinco prefixos. Sao
sessenta linhas e nao tem segredos.

O que isto **nao** e: nao e um cliente para producao, nao tem *pipelining*, nao
tem reconexao e nao fala RESP3. O publicador usa o cliente do BullMQ (ioredis),
que e outra coisa; este serve a suite.

## Como se sabe o que o BullMQ guarda

O BullMQ guarda cada *job* numa *hash* `bull:<fila>:<jobId>` e os pendentes numa
lista `bull:<fila>:wait`. A suite nao depende dessa forma para a asercao
principal — conta os *jobs* por `jobId`, que e o `event_id`, e esse e **contrato
nosso** (`docs/tecnica/06` §6.2) — mas depende dela para saber onde olhar. Se o
BullMQ mudar o prefixo, estes testes falham com «fila vazia», e e esse o sinal.
"""

from __future__ import annotations

import os
import socket


class FilaIndisponivel(RuntimeError):
    """Nao se chegou a fila."""


class RespInvalido(RuntimeError):
    """A resposta nao e RESP que este cliente saiba ler."""


#: Prefixo que o BullMQ poe em todas as chaves de uma fila.
PREFIXO = "bull"


class Fila:
    """Ligacao a fila. Usa-se como gestor de contexto."""

    def __init__(self, anfitriao: str | None = None, porta: int | None = None) -> None:
        self.anfitriao = anfitriao or os.environ.get("KAMBA_FILA_HOST", "127.0.0.1")
        porta_do_ambiente = os.environ.get("KAMBA_FILA_PORT", "")
        if porta is None and not porta_do_ambiente.isdigit():
            raise FilaIndisponivel(
                "KAMBA_FILA_PORT nao esta definida: `python db/gate_bd.py "
                "--suite tests_eventos` levanta a fila e define-a."
            )
        self.porta = porta or int(porta_do_ambiente)
        self._ligacao: socket.socket | None = None
        self._buffer = b""

    def __enter__(self) -> "Fila":
        self.ligar()
        return self

    def __exit__(self, *_) -> None:
        self.fechar()

    def ligar(self, espera: float = 10.0) -> None:
        try:
            self._ligacao = socket.create_connection(
                (self.anfitriao, self.porta), timeout=espera
            )
        except OSError as erro:
            raise FilaIndisponivel(f"{self.anfitriao}:{self.porta}: {erro}") from erro
        self._buffer = b""

    def fechar(self) -> None:
        if self._ligacao is not None:
            self._ligacao.close()
            self._ligacao = None

    # ------------------------------------------------------------ protocolo

    def _linha(self) -> bytes:
        assert self._ligacao is not None
        while b"\r\n" not in self._buffer:
            pedaco = self._ligacao.recv(65536)
            if not pedaco:
                raise FilaIndisponivel("a fila fechou a ligacao")
            self._buffer += pedaco
        linha, _, resto = self._buffer.partition(b"\r\n")
        self._buffer = resto
        return linha

    def _octetos(self, quantos: int) -> bytes:
        assert self._ligacao is not None
        while len(self._buffer) < quantos + 2:
            pedaco = self._ligacao.recv(65536)
            if not pedaco:
                raise FilaIndisponivel("a fila fechou a ligacao")
            self._buffer += pedaco
        dados = self._buffer[:quantos]
        self._buffer = self._buffer[quantos + 2 :]
        return dados

    def _resposta(self):
        linha = self._linha()
        marca, corpo = linha[:1], linha[1:]
        if marca in (b"+", b"-"):
            if marca == b"-":
                raise RespInvalido(corpo.decode("utf-8", "replace"))
            return corpo.decode("utf-8")
        if marca == b":":
            return int(corpo)
        if marca == b"$":
            tamanho = int(corpo)
            return None if tamanho < 0 else self._octetos(tamanho).decode("utf-8")
        if marca == b"*":
            quantos = int(corpo)
            return None if quantos < 0 else [self._resposta() for _ in range(quantos)]
        raise RespInvalido(f"prefixo desconhecido: {linha[:1]!r}")

    def comando(self, *partes: str):
        """Manda um comando e devolve a resposta."""
        if self._ligacao is None:
            raise FilaIndisponivel("a ligacao nao esta aberta")
        pedido = f"*{len(partes)}\r\n".encode()
        for parte in partes:
            octetos = parte.encode("utf-8")
            pedido += b"$%d\r\n%s\r\n" % (len(octetos), octetos)
        self._ligacao.sendall(pedido)
        return self._resposta()

    # -------------------------------------------------------------- consultas

    def ping(self) -> bool:
        return self.comando("PING") == "PONG"

    def esperar_viva(self, limite: float = 60.0) -> bool:
        """Religa e espera que a fila responda. Devolve se respondeu.

        Religar **e** esperar, e nao uma coisa e depois a outra: depois de um
        `docker start`, o proxy de porta do Docker aceita a ligacao antes de o
        servidor estar pronto, e o servidor fecha-a — o `ping` levantava
        `FilaIndisponivel` em vez de devolver `False`, e o laco de espera nao a
        apanhava (medido no CI, no criterio 4). Aqui qualquer falha e «ainda
        nao» e tenta-se outra vez.
        """
        import time as _time

        fim = _time.monotonic() + limite
        while _time.monotonic() < fim:
            try:
                self.fechar()
                self.ligar(espera=2.0)
                if self.ping():
                    return True
            except (FilaIndisponivel, RespInvalido, OSError):
                pass
            _time.sleep(0.5)
        return False

    def limpar(self) -> None:
        self.comando("FLUSHALL")

    def chaves(self, padrao: str) -> list[str]:
        """`KEYS`. Numa base de ensaio com milhares de chaves, chega."""
        return list(self.comando("KEYS", padrao) or [])

    def jobs(self, fila: str) -> set[str]:
        """Os `jobId` dos *jobs* que existem na fila.

        Tira-os dos nomes das chaves `bull:<fila>:<jobId>`, deixando de fora as
        chaves de controlo do BullMQ (`wait`, `meta`, `id`, `events`, ...), que
        se distinguem por **nao** serem um UUID. Os nossos `jobId` sao sempre o
        `event_id`, e esse e UUIDv7.
        """
        prefixo = f"{PREFIXO}:{fila}:"
        encontrados = set()
        for chave in self.chaves(f"{prefixo}*"):
            sufixo = chave[len(prefixo) :]
            if _e_uuid(sufixo):
                encontrados.add(sufixo)
        return encontrados

    def filas(self) -> set[str]:
        """Os nomes de fila que tem alguma chave."""
        nomes = set()
        for chave in self.chaves(f"{PREFIXO}:*"):
            resto = chave[len(PREFIXO) + 1 :]
            if ":" in resto:
                nomes.add(resto.rsplit(":", 1)[0])
        return nomes

    def pendentes(self, fila: str) -> int:
        """`LLEN bull:<fila>:wait`: quantos *jobs* esperam consumidor.

        **E este o numero que o criterio 3 pede**, e nao o tamanho de `jobs()`.
        As chaves do Redis sao unicas por definicao, pelo que
        `jobs(fila) == {event_id}` nao distingue «um *job*» de «o `jobId`
        existe»: a asercao nao podia falhar. O achado e da revisao adversarial
        (ANALISE-20, achado 3). A lista `wait` conta entradas, e duas entradas
        para o mesmo `event_id` aparecem como 2.
        """
        return int(self.comando("LLEN", f"{PREFIXO}:{fila}:wait") or 0)

    def espera(self, fila: str) -> list[str]:
        """A lista `wait` por inteiro, da cauda para a cabeca.

        O BullMQ empurra com `LPUSH` e consome com `BRPOPLPUSH`, pelo que o
        **fim** da lista e o proximo a sair. Devolve-se por ordem de saida, que e
        a ordem de entrega — e e a unica forma de verificar a ordem causal do
        agregado, que o criterio 7 pressupoe e nenhum teste media (ANALISE-20,
        achado 4).
        """
        chave = f"{PREFIXO}:{fila}:wait"
        bruto = self.comando("LRANGE", chave, "0", "-1") or []
        return list(reversed([str(x) for x in bruto]))

    def chaves_de(self, fila: str) -> list[str]:
        """Todas as chaves da fila, inclusive as de controlo. Para diagnostico."""
        return self.chaves(f"{PREFIXO}:{fila}:*")


def _e_uuid(texto: str) -> bool:
    import uuid as _uuid

    try:
        return str(_uuid.UUID(texto)) == texto
    except ValueError:
        return False
