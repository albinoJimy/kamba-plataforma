"""A tranca por conversa, contra o servidor (KAM-025 criterios 2 e 4).

Nada aqui se pode medir com uma ligacao so, e e por isso que a suite existe: a
segunda tomada do mesmo `pg_advisory_lock` na **mesma** sessao e concedida de
imediato — o PostgreSQL conta-as —, pelo que um teste com uma ligacao diz
«passou» sem ter medido exclusao nenhuma.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import textwrap
import time
import unittest
from pathlib import Path

from tests_agr.base import (
    SQL_DESTRANCAR_THREAD,
    SQL_TRANCAR_THREAD,
    ComAgr,
    thread_id_de,
)

RAIZ = Path(__file__).resolve().parents[2]

#: `pg_try_advisory_lock` e nao `pg_advisory_lock`: e a mesma chave e o mesmo
#: espaco de *locks*, mas devolve em vez de bloquear. **A aplicacao usa a
#: versao que espera** (criterio 2: a ordem de chegada preserva-se, e desistir
#: perdia turnos); aqui usa-se a que nao espera para **observar** quem tem a
#: tranca, que e o que um teste precisa de fazer sem ficar pendurado.
SQL_TENTAR = "SELECT pg_try_advisory_lock(hashtextextended(%s::text, 0)) AS consegui"

#: Os *locks* de tipo `advisory` que uma sessao detem, pelo `pg_locks`.
SQL_LOCKS_ADVISORY = """
  SELECT count(*) FROM pg_locks
   WHERE locktype = 'advisory' AND granted
"""


def _tentar(conexao, thread_id: str) -> bool:
    cursor = conexao.cursor()
    try:
        cursor.execute(SQL_TENTAR, (thread_id,))
        return bool(cursor.fetchone()[0])
    finally:
        cursor.close()


def _largar(conexao, thread_id: str) -> bool:
    cursor = conexao.cursor()
    try:
        cursor.execute(SQL_DESTRANCAR_THREAD, (thread_id,))
        return bool(cursor.fetchone()[0])
    finally:
        cursor.close()


class TestExclusaoMutua(ComAgr):
    def test_duas_sessoes_nao_tem_a_mesma_tranca(self) -> None:
        # O criterio 2, na sua forma minima e verificavel: a propriedade de que
        # «0 execucoes sobrepostas» depende.
        conversa = self.criar_conversa()
        primeira = self.ligacao_de_tranca()
        segunda = self.ligacao_de_tranca()

        cursor = primeira.cursor()
        cursor.execute(SQL_TRANCAR_THREAD, (conversa.thread_id,))
        cursor.fetchone()
        cursor.close()

        self.assertFalse(
            _tentar(segunda, conversa.thread_id),
            "a segunda sessao conseguiu a tranca que a primeira tem",
        )
        self.assertTrue(_largar(primeira, conversa.thread_id))
        self.assertTrue(
            _tentar(segunda, conversa.thread_id),
            "largada a tranca, a segunda sessao tem de a conseguir",
        )
        _largar(segunda, conversa.thread_id)

    def test_duas_conversas_diferentes_nao_se_travam(self) -> None:
        a = self.criar_conversa()
        b = self.criar_conversa()
        primeira = self.ligacao_de_tranca()
        segunda = self.ligacao_de_tranca()
        self.assertTrue(_tentar(primeira, a.thread_id))
        self.assertTrue(_tentar(segunda, b.thread_id))
        _largar(primeira, a.thread_id)
        _largar(segunda, b.thread_id)

    def test_a_tranca_sobrevive_ao_fim_da_instrucao(self) -> None:
        # E a diferenca entre `pg_advisory_lock` e `pg_advisory_xact_lock`, e e
        # a razao de ser da Decisao 2 do ADR-L004: em `autocommit` cada `SELECT`
        # e a sua propria transaccao, e um *lock* de transaccao largava aqui.
        conversa = self.criar_conversa()
        dona = self.ligacao_de_tranca()
        outra = self.ligacao_de_tranca()

        cursor = dona.cursor()
        cursor.execute(SQL_TRANCAR_THREAD, (conversa.thread_id,))
        cursor.fetchone()
        cursor.close()
        # Varias instrucoes depois, numa ligacao em `autocommit`.
        for _ in range(3):
            cursor = dona.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchone()
            cursor.close()

        self.assertFalse(_tentar(outra, conversa.thread_id))
        _largar(dona, conversa.thread_id)

    def test_a_chave_colide_com_a_do_lock_dos_modos(self) -> None:
        """A mesma conversa, trancada pelas duas chaves, e uma tranca so.

        E deliberado (ADR-L004, Decisao 2): o `SQL_TRANCAR_CONVERSA` do KAM-018
        hasheia `tenant_id || ':' || contact_id` e este hasheia o `thread_id`,
        que **e** esse texto. A colisao e o que faz uma transicao de modo em
        curso travar a entrada de um turno — e e uma afirmacao que so a base
        pode confirmar, porque depende de o `hashtextextended` dar o mesmo
        `bigint` para o mesmo texto.
        """
        conversa = self.criar_conversa()
        do_agr = self.ligacao_de_tranca()
        dos_modos = self.ligacao_de_tranca()

        cursor = do_agr.cursor()
        cursor.execute(SQL_TRANCAR_THREAD, (conversa.thread_id,))
        cursor.fetchone()
        cursor.close()

        # A forma do KAM-018: dois argumentos, concatenados com `:`.
        cursor = dos_modos.cursor()
        cursor.execute(
            "SELECT pg_try_advisory_lock("
            "  hashtextextended(%s::text || ':' || %s::text, 0)) AS consegui",
            (conversa.tenant_id, conversa.contact_id),
        )
        conseguiu = bool(cursor.fetchone()[0])
        cursor.close()
        self.assertFalse(
            conseguiu,
            "as duas chaves tem de colidir: senao um turno e uma transicao de "
            "modo correm ao mesmo tempo sobre a mesma conversa",
        )
        _largar(do_agr, conversa.thread_id)

    def test_destrancar_o_que_nao_e_nosso_devolve_falso(self) -> None:
        # E o `false` que o `trancas.py` transforma em `TrancaNaoLargadaError`:
        # o sintoma de um *pooler* em modo transaccao, que de outra forma nao da
        # erro nenhum — da exclusao mutua que nao exclui.
        conversa = self.criar_conversa()
        dona = self.ligacao_de_tranca()
        outra = self.ligacao_de_tranca()
        self.assertTrue(_tentar(dona, conversa.thread_id))
        self.assertFalse(_largar(outra, conversa.thread_id))
        _largar(dona, conversa.thread_id)


class TestMorteDoWorker(ComAgr):
    """Criterio 4: a tranca larga quando a ligacao morre. Com SIGKILL a serio."""

    def _filho_que_tranca(self, thread_id: str) -> subprocess.Popen:
        """Um processo que toma a tranca, diz que a tem, e fica a espera.

        Um processo e nao uma *thread*: o criterio 4 diz «morto com SIGKILL», e
        um SIGKILL nao se entrega a uma *thread*. O filho herda o ambiente, que
        e onde as credenciais da base estao — nunca na linha de comandos.
        """
        codigo = textwrap.dedent(
            """
            import sys
            sys.path.insert(0, %r)
            sys.path.insert(0, %r)
            from kamba_agr.ligacao import ligar_para_tranca
            from kamba_agr.consultas import SQL_TRANCAR_THREAD
            ligacao = ligar_para_tranca()
            cursor = ligacao.cursor()
            cursor.execute(SQL_TRANCAR_THREAD, (%r,))
            cursor.fetchone()
            print("tranquei", flush=True)
            # Fica. Quem o mata e o teste.
            import time
            while True:
                time.sleep(1)
            """
        ) % (
            str(RAIZ / "services" / "agr" / "src"),
            str(RAIZ / "libs" / "py-core" / "src"),
            thread_id,
        )
        return subprocess.Popen(
            [sys.executable, "-c", codigo],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ.copy(),
            text=True,
        )

    def test_um_sigkill_a_meio_do_turno_larga_a_tranca(self) -> None:
        conversa = self.criar_conversa()
        observador = self.ligacao_de_tranca()

        filho = self._filho_que_tranca(conversa.thread_id)
        self.addCleanup(self._garantir_morto, filho)
        linha = filho.stdout.readline().strip() if filho.stdout else ""
        self.assertEqual(linha, "tranquei", f"o filho nao tomou a tranca: {linha!r}")

        # Com o filho vivo, ninguem mais a tem.
        self.assertFalse(
            _tentar(observador, conversa.thread_id),
            "o filho tomou a tranca mas outra sessao conseguiu-a tambem",
        )

        # SIGKILL. No Windows, o `kill` do `subprocess` e um `TerminateProcess`,
        # que e igualmente nao-interceptavel: o processo nao corre `finally`
        # nenhum, nao larga a tranca, e quem a larga e o servidor ao ver a
        # tomada fechada. E a propriedade que se quer medir nas duas
        # plataformas.
        if hasattr(signal, "SIGKILL"):
            filho.send_signal(signal.SIGKILL)
        else:
            filho.kill()
        filho.wait(timeout=30)

        # O servidor pode levar um instante a notar a tomada fechada.
        livre = False
        fim = time.monotonic() + 30
        while time.monotonic() < fim:
            if _tentar(observador, conversa.thread_id):
                livre = True
                break
            time.sleep(0.2)
        self.assertTrue(
            livre,
            "a tranca ficou presa depois de o dono morrer: sem isto, o criterio "
            "4 obrigava a um temporizador, e um temporizador expira com o dono "
            "vivo (ADR-L004, Decisao 2)",
        )
        _largar(observador, conversa.thread_id)

    def _garantir_morto(self, filho: subprocess.Popen) -> None:
        if filho.poll() is None:
            filho.kill()
            filho.wait(timeout=30)
        for fluxo in (filho.stdout, filho.stderr):
            if fluxo is not None:
                fluxo.close()

    def test_a_ligacao_fechada_com_jeito_tambem_larga(self) -> None:
        # O caminho normal: um encerramento ordenado (`TrancaDeConversas.fechar`)
        # larga tudo o que a ligacao tivesse, sem precisar de `unlock`.
        conversa = self.criar_conversa()
        observador = self.ligacao_de_tranca()
        import ligacao as modulo_de_ligacao

        efemera = modulo_de_ligacao.ligar("app")
        efemera.autocommit = True
        self.assertTrue(_tentar(efemera, conversa.thread_id))
        self.assertFalse(_tentar(observador, conversa.thread_id))
        efemera.close()

        livre = False
        fim = time.monotonic() + 30
        while time.monotonic() < fim:
            if _tentar(observador, conversa.thread_id):
                livre = True
                break
            time.sleep(0.2)
        self.assertTrue(livre)
        _largar(observador, conversa.thread_id)


class TestOEspacoDeLocks(ComAgr):
    def test_a_sessao_nao_deixa_locks_atras_de_si(self) -> None:
        # Uma fuga de *locks* nao da erro: acumula linhas em `pg_locks` ate o
        # `max_locks_per_transaction` e, ai, rebenta uma transaccao que nao tem
        # nada a ver. E por isso que se conta.
        conversa = self.criar_conversa()
        conexao = self.ligacao_de_tranca()
        cursor = conexao.cursor()
        cursor.execute(SQL_LOCKS_ADVISORY)
        antes = int(cursor.fetchone()[0])
        cursor.close()

        for _ in range(20):
            cursor = conexao.cursor()
            cursor.execute(SQL_TRANCAR_THREAD, (conversa.thread_id,))
            cursor.fetchone()
            cursor.close()
            self.assertTrue(_largar(conexao, conversa.thread_id))

        cursor = conexao.cursor()
        cursor.execute(SQL_LOCKS_ADVISORY)
        depois = int(cursor.fetchone()[0])
        cursor.close()
        self.assertEqual(antes, depois, "ficaram locks advisory por largar")


if __name__ == "__main__":
    unittest.main()
