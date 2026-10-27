"""Uma base falsa para a subscricao de eventos (KAM-038).

Nao e uma base de dados: e o **minimo** que a decisao deste ticket pergunta a
uma, com as tres propriedades que a decisao depende e sem nenhuma que ela nao
use. As tres, por extenso, porque sao elas que tornam a bateria honesta:

1. **`ON CONFLICT (consumer, event_id) DO NOTHING` nao escreve duas vezes.** O
   `_trinco` serializa a leitura e a escrita da marca. Sem isso, cinco entregas
   em paralelo escreviam cinco linhas e o criterio 2 passava por nao haver
   corrida nenhuma.

   **E isto NAO e o que o indice unico da `0005` faz, e a diferenca importa.**
   No PostgreSQL um segundo `INSERT ... ON CONFLICT DO NOTHING` **bloqueia** ate
   a primeira transaccao confirmar ou desfazer; aqui a marca e visivel antes do
   `COMMIT`, e so o `rollback` a retira. Consequencia: se a primeira transaccao
   reverter, nesta base os outros quatro ja responderam «duplicado» **sem
   efeito** e a marca desaparece — o evento fica sem efeito em nenhum; no
   servidor real o segundo esperava, inseria e corria o efeito. A propriedade
   «cinco entregas concorrentes, um efeito» **sob corrida a serio** prova-se em
   `db/tests_agr/test_eventos.py`, com cinco ligacoes. A primeira versao desta
   nota afirmava a equivalencia; achado da revisao adversarial.
2. **A RLS e por `app.tenant_id`.** Cada ligacao guarda o contexto que lhe foi
   posto, e as leituras **filtram por ele**. Sem isso, o envelope forjado do
   criterio 4 encontrava a conversa de outro *tenant* e o teste media o
   predicado da consulta em vez do isolamento.
3. **O `rowcount` de um `INSERT ... DO NOTHING` e zero quando nao escreve.** E
   esse zero que o `consumir` do KAM-006 le como «duplicado».

O que ela **nao** faz, e fica dito para que ninguem leia esta bateria como
prova do que nao prova: nao interpreta SQL (compara cadeias), nao tem
transaccoes a serio (o `rollback` desfaz o que esta marcado nesta transaccao e
mais nada), e nao tem indices parciais. A prova de que o SQL **corre** e da
*suite* do *gate* 8, contra PostgreSQL.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

from kamba_agr.eventos.consultas import SQL_ABRIR_DLQ, SQL_CONVERSA_DO_CONTACTO
from kamba_core.eventos.consumo import SQL_MARCAR_CONSUMIDO, SQL_ULTIMO_SEQ


@dataclass
class LinhaDaConversa:
    """O que a `platform.conversations` tem de ter para este ticket."""

    id: str
    tenant_id: str
    contact_id: str
    modo: str = "bot"
    handoff_a_espera: bool = False
    last_inbound_at: float | None = None


@dataclass
class Servidor:
    """O estado partilhado por todas as ligacoes. E a «base»."""

    conversas: list[LinhaDaConversa] = field(default_factory=list)
    consumidos: dict[tuple[str, str], dict] = field(default_factory=dict)
    dlq: list[dict] = field(default_factory=list)
    #: `(tenant_id, modulo) -> permitido`. A omissao permite, e a bateria que
    #: mede a recusa poe o par a `False`: o que esta classe modela e a resposta
    #: da base, e falhar fechada e do `check_entitlement` e nao daqui.
    entitlements: dict[tuple[str, str], bool] = field(default_factory=dict)
    #: Quantas ligacoes se abriram e quantas se fecharam. Uma diferenca que
    #: cresce e uma fuga de tomadas.
    abertas: int = 0
    fechadas: int = 0
    trinco: threading.Lock = field(default_factory=threading.Lock)

    def abrir(self) -> "LigacaoFalsa":
        # Sob o trinco: as ligacoes abrem em *threads* (tudo o que toca a base
        # vai a um executor), e um contador de fugas com corrida nao conta
        # fugas. Achado da revisao adversarial.
        with self.trinco:
            self.abertas += 1
        return LigacaoFalsa(self)


class CursorFalso:
    def __init__(self, ligacao: "LigacaoFalsa") -> None:
        self._ligacao = ligacao
        self._linhas: list[tuple] = []
        self.description: list[tuple] | None = None
        self.rowcount = 0
        self.fechado = False

    def execute(self, sql: str, parametros: tuple = ()) -> None:
        self._ligacao.sql.append(sql)
        texto = sql.strip()
        if "set_config" in texto:
            self._ligacao.tenant = str(parametros[0])
            self._uma_linha([("set_config",)], [(str(parametros[0]),)])
            return
        if texto == SQL_MARCAR_CONSUMIDO.strip():
            self._marcar(parametros)
            return
        if texto == SQL_ULTIMO_SEQ.strip():
            self._ultimo_seq(parametros)
            return
        if texto == SQL_ABRIR_DLQ.strip():
            self._dlq(parametros)
            return
        if texto == SQL_CONVERSA_DO_CONTACTO.strip():
            self._conversa(parametros)
            return
        if "platform.entitlements" in texto or "entitlement" in texto.lower():
            self._entitlement(parametros)
            return
        raise AssertionError(f"SQL que a base falsa nao conhece:\n{sql}")

    # ------------------------------------------------------------- tabelas

    def _marcar(self, parametros: tuple) -> None:
        consumer, event_id = str(parametros[0]), str(parametros[1])
        with self._ligacao.servidor.trinco:
            if (consumer, event_id) in self._ligacao.servidor.consumidos:
                self.rowcount = 0
            else:
                self._ligacao.servidor.consumidos[(consumer, event_id)] = {
                    "consumer": consumer,
                    "event_id": event_id,
                    "tenant_id": str(parametros[2]),
                    "agregado_tipo": parametros[3],
                    "agregado_id": parametros[4],
                    "agregado_seq": parametros[5],
                }
                self._ligacao.marcadas.append((consumer, event_id))
                self.rowcount = 1
        self.description = None
        self._linhas = []

    def _ultimo_seq(self, parametros: tuple) -> None:
        consumer, tipo, identificador, excluir = (str(p) for p in parametros)
        valores = [
            linha["agregado_seq"]
            for (c, e), linha in self._ligacao.servidor.consumidos.items()
            if c == consumer
            and str(linha["agregado_tipo"]) == tipo
            and str(linha["agregado_id"]) == identificador
            and e != excluir
        ]
        self._uma_linha([("ultimo",)], [(max(valores) if valores else None,)])

    def _dlq(self, parametros: tuple) -> None:
        consumer, event_id = str(parametros[0]), str(parametros[1])
        ja_aberta = any(
            entrada["consumer"] == consumer and entrada["event_id"] == event_id
            for entrada in self._ligacao.servidor.dlq
        )
        if ja_aberta:
            self.rowcount = 0
        else:
            self._ligacao.servidor.dlq.append(
                {
                    "consumer": consumer,
                    "event_id": event_id,
                    "tipo": parametros[2],
                    "versao": parametros[3],
                    "tenant_id": parametros[4],
                    "envelope": parametros[5],
                    "erro": parametros[6],
                    "tentativas": parametros[7],
                }
            )
            self.rowcount = 1
        self.description = None
        self._linhas = []

    def _conversa(self, parametros: tuple) -> None:
        tenant_id, contact_id = str(parametros[0]), str(parametros[1])
        candidatas = [
            linha
            for linha in self._ligacao.servidor.conversas
            # **A RLS primeiro, e o predicado depois.** As duas condicoes sao a
            # mesma neste caso e nao sao a mesma coisa: a primeira e o
            # isolamento (`app.tenant_id`) e a segunda e a consulta. Separa-las
            # aqui e o que faz o teste do envelope forjado medir o isolamento.
            if linha.tenant_id == self._ligacao.tenant
            and linha.tenant_id == tenant_id
            and linha.contact_id == contact_id
        ]
        candidatas.sort(key=lambda l: (-(l.last_inbound_at or -1e18), l.id))
        if not candidatas:
            self._uma_linha([("conversa",), ("modo",), ("handoff_a_espera",)], [])
            return
        escolhida = candidatas[0]
        self._uma_linha(
            [("conversa",), ("modo",), ("handoff_a_espera",)],
            [(escolhida.id, escolhida.modo, escolhida.handoff_a_espera)],
        )

    def _entitlement(self, parametros: tuple) -> None:
        """As quatro colunas do `SQL_ENTITLEMENT`, pela ordem de la.

        O `permitido` **vem da coluna** e nao se recalcula aqui, como o
        `_montar` do KAM-009 exige: a regra dos tres estados do *tenant* vive no
        SQL, e uma segunda copia dela nesta base falsa fazia o teste medir a
        copia.
        """
        tenant_id, modulo = str(parametros[0]), str(parametros[1])
        if self._ligacao.tenant != tenant_id:
            self._uma_linha(
                [("estado_tenant",), ("tem_linha",), ("ativo",), ("permitido",)], []
            )
            return
        permitido = self._ligacao.servidor.entitlements.get((tenant_id, modulo), True)
        self._uma_linha(
            [("estado_tenant",), ("tem_linha",), ("ativo",), ("permitido",)],
            [("ativo", True, permitido, permitido)],
        )

    # ------------------------------------------------------------- DB-API

    def _uma_linha(self, descricao: list[tuple], linhas: list[tuple]) -> None:
        self.description = descricao
        self._linhas = linhas
        self.rowcount = len(linhas)

    def fetchone(self):
        return self._linhas[0] if self._linhas else None

    def fetchall(self):
        return list(self._linhas)

    def close(self) -> None:
        self.fechado = True


class LigacaoFalsa:
    """Uma ligacao DB-API: `cursor`, `commit`, `rollback`, `close`."""

    autocommit = False

    def __init__(self, servidor: Servidor) -> None:
        self.servidor = servidor
        self.tenant: str | None = None
        self.sql: list[str] = []
        self.commits = 0
        self.rollbacks = 0
        self.fechada = False
        #: As marcas escritas **nesta** transaccao, para o `rollback` as
        #: desfazer. E o minimo de transaccao que o criterio 2 precisa: sem ele,
        #: um efeito que levanta deixava a marca escrita e a re-entrega lia
        #: «duplicado» — o efeito nunca mais acontecia.
        self.marcadas: list[tuple[str, str]] = []

    def cursor(self) -> CursorFalso:
        return CursorFalso(self)

    def commit(self) -> None:
        self.commits += 1
        self.marcadas = []

    def rollback(self) -> None:
        self.rollbacks += 1
        with self.servidor.trinco:
            for chave in self.marcadas:
                self.servidor.consumidos.pop(chave, None)
        self.marcadas = []

    def close(self) -> None:
        self.fechada = True
        with self.servidor.trinco:
            self.servidor.fechadas += 1


class TrancaFalsa:
    """A `TrancaDeConversas`, com a exclusao e o registo de quem a tomou."""

    def __init__(self) -> None:
        import asyncio
        import contextlib

        self._por_thread: dict[str, asyncio.Lock] = {}
        self.tomadas: list[str] = []
        self.sobrepostas = 0
        self._dentro: set[str] = set()
        self._asyncio = asyncio
        self._contextlib = contextlib

    def tomar(self, thread_id: str):
        trinco = self._por_thread.setdefault(thread_id, self._asyncio.Lock())

        @self._contextlib.asynccontextmanager
        async def _tomar():
            async with trinco:
                if thread_id in self._dentro:
                    self.sobrepostas += 1
                self._dentro.add(thread_id)
                self.tomadas.append(thread_id)
                try:
                    yield
                finally:
                    self._dentro.discard(thread_id)

        return _tomar()


class OutboundEspiao:
    """O Outbound, com memoria do que lhe pediram e do que devolveu."""

    def __init__(self, desfecho: str = "livre") -> None:
        self.desfecho = desfecho
        self.chamadas: list[dict[str, Any]] = []

    def notificar(self, *, tenant_id: str, notificacao, chave: str) -> str:
        self.chamadas.append(
            {"tenant_id": tenant_id, "notificacao": notificacao, "chave": chave}
        )
        return self.desfecho


class HndEspiao:
    """O HND. **Nunca** devia receber nada que seja do caminho do cliente."""

    def __init__(self) -> None:
        self.chamadas: list[dict[str, Any]] = []

    def avisar(self, *, tenant_id: str, motivo: str, chave: str) -> None:
        self.chamadas.append({"tenant_id": tenant_id, "motivo": motivo, "chave": chave})


class ContactoFixo:
    """Resolve o contacto de qualquer agregado para o mesmo valor."""

    def __init__(self, contact_id: str) -> None:
        self.contact_id = contact_id
        self.pedidos: list[tuple[str, str]] = []

    def contacto_de(self, agregado_tipo: str, agregado_id: str) -> str:
        self.pedidos.append((agregado_tipo, agregado_id))
        return self.contact_id
