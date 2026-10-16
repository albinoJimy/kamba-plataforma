"""Base da suite do consumidor: PostgreSQL e fila reais (KAM-006).

Herda o que o KAM-005 construiu — `tests_eventos.base.ComFila` levanta a base,
liga a fila, limpa tudo entre testes e sabe lancar um processo Node — e
acrescenta o que e deste ticket: lancar o **consumidor** e a **reposicao**, ler
a janela de deduplicacao e a DLQ, e publicar um evento de verdade para o
consumidor o apanhar.

Porque herda em vez de copiar: o `node.lancar` tem dois caminhos (com `node` no
`PATH` e sem ele, por contentor na rede do gate) e isso nao se duplica. O que
muda e o programa que se lanca e as tabelas que se leem.

## Dois papeis, e nao um

O consumidor corre como **`kamba_app`** e a reposicao como **`kamba_batch`**, e
isto nao e detalhe de configuracao:

* `kamba_app` e o que tem `INSERT` em `events_consumed`, na DLQ e em
  `evt_acoes` (revisao 0005). Correr o consumidor como `kamba_batch` falhava com
  `permission denied` — e foi assim que o defeito apareceu, porque a primeira
  versao desta suite usava a ligacao do publicador;
* `kamba_app` e `NOBYPASSRLS`, pelo que todo o consumo precisa de contexto de
  tenant. Quem o poe e o `consumir()`, a partir do envelope;
* a reposicao procura o que se perdeu em **todos** os tenants (§6.5), e isso so
  `kamba_batch` pode ver.

A matriz completa de privilegios tem suite propria
(`db/tests/test_privilegios.py`), que a mede coluna a coluna; o que esta suite
prova e que o laco funciona com os papeis que a revisao deu.

## O relogio acelerado

A escada do §6.4 e 1 s, 5 s, 30 s, 2 min, 10 min: esgotar as seis tentativas
custa 756 s de espera real, e dois testes fazem-no. Os «Testes Requeridos» do
ticket pedem relogio acelerado, e e o que se usa — `ESCADA_ACELERADA`, pelo
`KAMBA_CON_ESCADA`. Os **valores** da escada de producao provam-se noutro sitio
(`packages/core-ts/tests/eventos.consumo.test.ts` e
`libs/py-core/tests/test_eventos_consumo.py`, `TestEscada`); o que se prova com
fila real e a **contagem** — seis tentativas, depois uma entrada na DLQ —, que e
o que o criterio 2 pede e o que nenhum teste sem fila consegue dizer.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from tests_eventos import node  # noqa: E402
from tests_eventos.base import CONSUMER, TIPO, ComFila, esperar_por  # noqa: E402

__all__ = ["CONSUMER", "ESCADA_ACELERADA", "ESPERA", "TIPO", "ComConsumidor", "esperar_por"]

#: Quanto se espera por um consumo. Generoso: o `node` arranca num contentor,
#: liga-se a base e a fila, e so depois comeca a trabalhar.
ESPERA = 90.0

#: A escada do relogio acelerado, em milissegundos. Cinco degraus, como a de
#: producao — o que muda e a duracao, nao o numero de tentativas, que e o que o
#: criterio 2 mede. 300 ms e acima da latencia de uma transacao na base do gate
#: e abaixo do que faz a suite esperar: cinco degraus somam 1,5 s.
ESCADA_ACELERADA = (300, 300, 300, 300, 300)

#: Quanto tempo se espera por uma entrada na DLQ.
#:
#: Dois caminhos, com dois tempos, e o maior manda. Uma **falha tecnica** recua
#: pela escada acelerada: cinco esperas de 300 ms, ~2 s. Um **`Adiar`** traz o
#: seu proprio atraso — os 5 s do §6.3 — e a escada acelerada nao lhe toca, de
#: proposito: o valor e do documento e o que o teste verifica e o desfecho, nao
#: a duracao. Cinco adiamentos sao 25 s. Com 120 s ha folga de quase cinco
#: vezes sobre o pior caso, para o contentor sob carga.
ESPERA_DA_DLQ = 120.0


class ComConsumidor(ComFila):
    """Tudo o que a `ComFila` da, mais o consumidor e as tabelas do consumo."""

    def setUp(self) -> None:
        super().setUp()
        # A `ComFila` limpa as tabelas do KAM-005; as do KAM-006 sao deste
        # ticket e limpam-se aqui, pela ordem das chaves estrangeiras.
        self._limpar_consumo()
        self.addCleanup(self._limpar_consumo)

    def _limpar_consumo(self) -> None:
        self.cursor.execute(
            "DELETE FROM platform.evt_dlq_aprovacoes a USING platform.events_dlq d "
            "WHERE a.dlq_id = d.id"
        )
        for tabela in ("events_dlq", "events_consumed", "evt_acoes"):
            self.cursor.execute(f"DELETE FROM platform.{tabela}")

    # ------------------------------------------------------------ processos

    def lancar_consumidor(self, rotulo: str = "c", **extra: str) -> node.Processo:
        """O `consumidor_runner.ts`, como `kamba_app` e com relogio acelerado.

        Quem quiser a escada de producao passa `KAMBA_CON_ESCADA=""`; nenhum
        teste desta suite o faz, e a razao esta na docstring do modulo.
        """
        ambiente = {
            "KAMBA_CON_ROTULO": rotulo,
            "KAMBA_CONSUMER": CONSUMER,
            "KAMBA_CONSUMIDOR_DB_URL": node.url_da_base(
                na_rede=self._na_rede(), papel="app"
            ),
            "KAMBA_CON_ESCADA": ",".join(str(ms) for ms in ESCADA_ACELERADA),
            **extra,
        }
        processo = node.lancar(
            ["tests_bd/consumidor_runner.ts"],
            ambiente,
            rotulo=f"con{rotulo}",
            registo=self.registos / f"con{rotulo}.log",
            variavel_do_registo="KAMBA_CON_REGISTO",
        )
        self.processos.append(processo)
        return processo

    def repor_uma_vez(self, **extra: str) -> node.Processo:
        """O `reconciliador_runner.ts`, uma passagem, sem carencia.

        Sem carencia (`KAMBA_RECON_CARENCIA=0`) porque o §6.5 so considera
        perdido o que tem mais de dez minutos: com o valor de producao, cada
        verificacao do criterio 8 esperava dez minutos reais. E o relogio
        acelerado que os «Testes Requeridos» pedem, e a carencia tem prova
        propria — `TestCarencia`, neste ficheiro de testes.
        """
        ambiente = {
            "KAMBA_CONSUMIDOR_OPS_DB_URL": node.url_da_base(
                na_rede=self._na_rede(), papel="batch"
            ),
            "KAMBA_RECON_CARENCIA": "0",
            "KAMBA_RECON_UMA_VEZ": "1",
            **extra,
        }
        processo = node.lancar(
            ["tests_bd/reconciliador_runner.ts"],
            ambiente,
            rotulo="recon",
            registo=self.registos / "recon.log",
            variavel_do_registo="KAMBA_RECON_REGISTO",
        )
        self.processos.append(processo)
        return processo

    @staticmethod
    def _na_rede() -> bool:
        """O mesmo criterio do `node.lancar`: sem `node` no `PATH`, vai por contentor."""
        import shutil

        return shutil.which("node") is None

    def esperar_arranque(self, processo: node.Processo, limite: float = ESPERA) -> bool:
        """Espera ate o consumidor **escrever** que arrancou, nao por um `sleep`."""
        return esperar_por(
            lambda: any(
                linha.get("evento") == "arrancou" for linha in processo.linhas()
            ),
            limite,
        )

    def esperar_fim(self, processo: node.Processo, limite: float = ESPERA) -> bool:
        """Espera que o processo termine por si. Para o `--uma-vez` da reposicao."""
        return esperar_por(lambda: not processo.vivo(), limite)

    @staticmethod
    def desfechos(processo: node.Processo, event_id: str | None = None) -> list[str]:
        """Os desfechos que o consumidor **escreveu**, pela ordem em que correram.

        E a unica forma de contar tentativas de fora do processo: a base guarda
        o estado final (a entrada na DLQ com `tentativas = 6`), e nao a
        sequencia que levou la. Com isto, o criterio 2 verifica-se pelos dois
        lados — cinco `adiado` e um `dlq`, e a linha da DLQ a dizer 6.

        As falhas tecnicas **nao** aparecem aqui, e e de proposito: o
        `processar()` relanca-as sem desfecho, porque nao ha decisao a registar.
        """
        linhas = [
            linha
            for linha in processo.linhas()
            if linha.get("evento") == "consumo"
            and (event_id is None or linha.get("event_id") == event_id)
        ]
        return [str(linha.get("desfecho")) for linha in linhas]

    def esquecer_na_fila(self, event_id: str, consumer: str = CONSUMER) -> None:
        """Apaga da fila tudo o que diz respeito a este evento.

        E a fila a esquecer — o que o Redis faz quando perde dados, e o que o
        BullMQ faz quando a retencao de concluidos passa. Precisa-se disto para
        **forcar uma segunda entrega**: o `add` do BullMQ e idempotente por
        `jobId` e, com o *job* concluido ainda guardado (dez mil, por
        `MANTER_CONCLUIDOS`), uma republicacao do outbox era simplesmente
        ignorada — e um teste de re-entrega que nao re-entrega nada passava sem
        provar nada.
        """
        fila = self.nome_da_fila(event_id, consumer)
        self.fila.comando("DEL", f"bull:{fila}:{event_id}")
        for conjunto in ("completed", "failed"):
            self.fila.comando("ZREM", f"bull:{fila}:{conjunto}", event_id)

    def republicar(self, event_id: str) -> None:
        """Devolve a linha do outbox ao estado «por publicar».

        O arquivo tem `ON CONFLICT DO NOTHING` (KAM-005), pelo que publicar
        duas vezes nao duplica nada em `events_log`.
        """
        self.cursor.execute(
            "UPDATE platform.events_outbox "
            "   SET publicado_at = NULL, tentativas = 0, proxima_tentativa_at = now() "
            " WHERE event_id = %s",
            (event_id,),
        )

    # -------------------------------------------------------------- leituras

    def consumidos(self, consumer: str = CONSUMER) -> int:
        self.cursor.execute(
            "SELECT count(*) FROM platform.events_consumed WHERE consumer = %s",
            (consumer,),
        )
        return int(self.cursor.fetchone()[0])

    def efeitos(self) -> int:
        """Quantas linhas o efeito `conta` escreveu (uma por efeito aplicado)."""
        self.cursor.execute(
            "SELECT count(*) FROM platform.evt_acoes WHERE accao = 'efeito'"
        )
        return int(self.cursor.fetchone()[0])

    def na_dlq(self, consumer: str = CONSUMER) -> list[dict]:
        self.cursor.execute(
            "SELECT id, event_id::text, tipo, versao, erro, tentativas, estado, envelope "
            "  FROM platform.events_dlq WHERE consumer = %s ORDER BY id",
            (consumer,),
        )
        colunas = (
            "id",
            "event_id",
            "tipo",
            "versao",
            "erro",
            "tentativas",
            "estado",
            "envelope",
        )
        return [dict(zip(colunas, linha)) for linha in self.cursor.fetchall()]

    def publicar(self, quantos: int = 1, **kwargs) -> list[str]:
        """Emite e **publica**: o evento fica na fila e no arquivo.

        O consumidor le o envelope do `events_log`, e por isso emitir sem
        publicar nao chega — o publicador e que arquiva. Lanca-se um publicador,
        espera-se que publique, e mata-se: o que esta suite prova e o consumo.
        """
        identificadores = self.emitir(quantos, **kwargs)
        publicador = self.lancar_publicador("p")
        self.assertTrue(
            esperar_por(lambda: self.pendentes() == 0, ESPERA),
            f"o publicador nao publicou{self.diagnostico()}",
        )
        publicador.parar()
        return identificadores


def exigir_ambiente() -> None:
    """A suite precisa de fila; sem ela **falha**, e nao salta."""
    if not os.environ.get("KAMBA_FILA_PORT", "").isdigit():
        raise AssertionError(
            "KAMBA_FILA_PORT nao esta definida: corra "
            "`python db/gate_bd.py --suite tests_eventos_consumo`."
        )
