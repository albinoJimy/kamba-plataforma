"""Base da suite de eventos: PostgreSQL e fila reais, os dois descartaveis.

O que esta suite prova, e nao se prova em lado nenhum senao aqui: os criterios
3, 4, 5 e 8 do KAM-005. Sao propriedades de **sistema** — um processo morto a
meio, a fila parada, dois processos a disputar a lideranca, e o atraso sob carga
— e nenhuma se mede com uma fila em memoria.

O trinco e o mesmo das outras suites: a base tem de se chamar `kamba_gate8`. E
ha um segundo: sem `KAMBA_FILA_PORT` a suite **falha**, nao salta. Num gate,
saltar e falhar.
"""

from __future__ import annotations

import json
import os
import time
import unittest
import uuid
from pathlib import Path

import ligacao
from tests.base import exigir_base_descartavel
from tests_eventos import fila as fila_mod
from tests_eventos import node

#: Consumidor de ensaio. Um nome, nao uma lista: os consumidores reais nascem
#: com o KAM-006 e nao se inventam aqui.
CONSUMER = "ensaio"
#: Segundo consumidor, para a *fan-out* e o roteamento por finalidade.
CONSUMER_ANALITICO = "ensaio-dat"

TIPO = "order.created"


def esperar_por(condicao, limite: float, intervalo: float = 0.2) -> bool:
    """Espera ate `condicao()` ou ate `limite` segundos. Devolve se aconteceu."""
    fim = time.monotonic() + limite
    while time.monotonic() < fim:
        if condicao():
            return True
        time.sleep(intervalo)
    return condicao()


class ComFila(unittest.TestCase):
    """Base e fila prontas, subscricoes semeadas, tudo limpo entre testes."""

    @classmethod
    def setUpClass(cls) -> None:
        exigir_base_descartavel()
        if not os.environ.get("KAMBA_FILA_PORT", "").isdigit():
            raise AssertionError(
                "KAMBA_FILA_PORT nao esta definida: a suite de eventos precisa de "
                "uma fila real. Corra `python db/gate_bd.py --suite tests_eventos`."
            )
        import bootstrap

        bootstrap.aplicar()
        from tests.base import alembic_ok, em_head

        if not em_head():
            alembic_ok("upgrade", "head")
        cls._admin = ligacao.ligar("admin")
        cls._admin.autocommit = True

    @classmethod
    def tearDownClass(cls) -> None:
        cls._admin.close()

    def setUp(self) -> None:
        self.cursor = self._admin.cursor()
        self.fila = fila_mod.Fila()
        self.fila.ligar()
        self.addCleanup(self.fila.fechar)
        self.fila.limpar()
        self._limpar_base()
        self.addCleanup(self._limpar_base)
        self.tenant = str(uuid.uuid4())
        self.processos: list[node.Processo] = []
        import shutil
        import tempfile

        # `mkdtemp` e nao `TemporaryDirectory`: em Windows um ficheiro com
        # descritor aberto nao se apaga, e a limpeza do gestor de contexto
        # levantava `WinError 32` **como erro de teste**, mascarando o resultado
        # de dezoito testes (medido). Aqui a limpeza nao pode falhar: o que
        # importa e o teste, nao o directorio temporario.
        self.registos = Path(tempfile.mkdtemp(prefix="kamba-eventos-"))
        self.addCleanup(lambda: shutil.rmtree(self.registos, ignore_errors=True))
        # Depois do `rmtree` na lista, e por isso **antes** dele a correr: o
        # `addCleanup` corre pela ordem inversa, e os processos tem de morrer
        # antes de se tentar apagar o que eles tem aberto.
        self.addCleanup(self._parar_processos)

    def _limpar_base(self) -> None:
        for tabela in ("events_outbox", "events_log", "evt_agregado_seq"):
            self.cursor.execute(f"DELETE FROM platform.{tabela}")
        self.cursor.execute("DELETE FROM platform.evt_subscricoes")

    def _parar_processos(self) -> None:
        for processo in self.processos:
            if processo.vivo():
                processo.matar()

    # ------------------------------------------------------------ subscricoes

    def subscrever(
        self,
        consumer: str = CONSUMER,
        tipo: str = TIPO,
        finalidade: str = "transacao",
        versao_max: int = 1,
        activo: bool = True,
    ) -> None:
        self.cursor.execute(
            "INSERT INTO platform.evt_subscricoes "
            "(consumer, tipo, versao_max, finalidade, activo) VALUES (%s, %s, %s, %s, %s)",
            (consumer, tipo, versao_max, finalidade, activo),
        )

    # ---------------------------------------------------------------- eventos

    def agregado_novo(self) -> str:
        """Um identificador de agregado **sem digitos**, e a razao e um defeito.

        A guarda de PII do `docs/tecnica/06` §6.1 e
        `\\+?244 ?9[0-9]{8}` — com o `+` **opcional**. Logo, qualquer corrida de
        doze digitos que comece por `2449` faz `evt_emitir` recusar o evento, e
        um identificador hexadecimal de 32 caracteres contem uma dessas de vez
        em quando. Aconteceu na medicao de carga: ao evento ~8 000 de 15 000, o
        `evt_emitir` levantou `check_violation` sobre um `agg-<hex>` que nao
        tinha telefone nenhum (registado em `docs/eventos.md` §3 e na decisao
        aberta 11).

        A suite usa letras para que o que se mede seja o publicador, e nao a
        taxa de falsos positivos da guarda. O falso positivo em si tem teste
        proprio, em `db/tests/test_eventos_schema.TestGuardaDePii`.
        """
        import secrets
        import string

        letras = "".join(
            secrets.choice(string.ascii_lowercase) for _ in range(24)
        )
        return f"agg-{letras}"

    def emitir(
        self,
        quantos: int = 1,
        agregado: str | None = None,
        finalidades: tuple[str, ...] = ("transacao",),
        versao: int = 1,
    ) -> list[str]:
        """Emite `quantos` eventos e devolve os `event_id`, pela ordem de emissao."""
        identificadores = []
        for indice in range(quantos):
            alvo = agregado or self.agregado_novo()
            self.cursor.execute(
                "SELECT platform.evt_emitir(%s, %s::smallint, %s, 'order', %s, "
                "%s::jsonb, 'P1', %s::text[])",
                (
                    TIPO,
                    versao,
                    self.tenant,
                    alvo,
                    json.dumps({"order_id": alvo, "n": indice}),
                    list(finalidades),
                ),
            )
            identificadores.append(str(self.cursor.fetchone()[0]))
        return identificadores

    def pendentes(self) -> int:
        self.cursor.execute(
            "SELECT count(*) FROM platform.events_outbox WHERE publicado_at IS NULL"
        )
        return int(self.cursor.fetchone()[0])

    def publicados(self) -> int:
        self.cursor.execute(
            "SELECT count(*) FROM platform.events_outbox WHERE publicado_at IS NOT NULL"
        )
        return int(self.cursor.fetchone()[0])

    def arquivados(self) -> int:
        self.cursor.execute("SELECT count(*) FROM platform.events_log")
        return int(self.cursor.fetchone()[0])

    def particao_de(self, event_id: str) -> int:
        self.cursor.execute(
            "SELECT particao FROM platform.events_outbox WHERE event_id = %s",
            (event_id,),
        )
        return int(self.cursor.fetchone()[0])

    def nome_da_fila(self, event_id: str, consumer: str = CONSUMER) -> str:
        return f"evt.{consumer}.p{self.particao_de(event_id)}"

    def recuo_de(self, event_id: str) -> tuple[int, bool]:
        """(`tentativas`, a proxima tentativa esta no futuro?)"""
        self.cursor.execute(
            "SELECT tentativas, proxima_tentativa_at > now() "
            "  FROM platform.events_outbox WHERE event_id = %s",
            (event_id,),
        )
        linha = self.cursor.fetchone()
        return int(linha[0]), bool(linha[1])

    # ------------------------------------------------------------- processos

    def lancar_publicador(self, rotulo: str = "a", **extra: str) -> node.Processo:
        ambiente = {"KAMBA_PUB_ROTULO": rotulo, **extra}
        processo = node.lancar(
            ["tests_bd/publicador_runner.ts"],
            ambiente,
            rotulo=f"pub{rotulo}",
            registo=self.registos / f"{rotulo}.log",
        )
        self.processos.append(processo)
        return processo

    def diagnostico(self) -> str:
        """O que cada publicador escreveu. Vai nas mensagens de falha.

        Sem isto, uma falha dizia «`tentativas` nao recuou» e mais nada — e a
        causa (um publicador que morreu ao arrancar, uma ligacao recusada) ficava
        invisivel. Aconteceu, e e a razao de este metodo existir.
        """
        return "".join(processo.diagnostico() for processo in self.processos)

    def esperar_lider(self, processo: node.Processo, limite: float) -> bool:
        """Espera que `processo` **diga** que e lider, lendo o que escreveu.

        Pelo que ele escreve, e nao por um `sleep`: um `sleep` de 2 s que
        passasse sem ele ser lider provava o contrario do que o criterio 5 pede.
        """
        def e_lider() -> bool:
            for dados in processo.linhas():
                if dados.get("evento") == "lideranca" and dados.get("lider") is True:
                    return True
            return False

        return esperar_por(e_lider, limite, intervalo=0.2)
