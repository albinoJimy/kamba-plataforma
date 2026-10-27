"""A subscricao de eventos contra a base (KAM-038, criterios 2, 3 e 4).

O que esta suite prova, e nao se prova em lado nenhum senao aqui:

| Criterio | A propriedade, e porque e que precisa da base |
|---|---|
| 2 | O `ON CONFLICT (consumer, event_id) DO NOTHING` e **atomico entre sessoes**. Cinco entregas em paralelo numa base falsa provam o trinco do duplo; so o servidor prova o indice unico |
| 2 | A marca e o efeito estao na **mesma transaccao**: um `ROLLBACK` leva a marca com ele. Uma base falsa nao tem transaccoes a serio |
| 2 | O indice **parcial** `events_dlq_aberta_uq` existe e e so sobre `estado = 'aberta'`: a reentrada e idempotente entre abertas e um ciclo novo depois de uma resolucao abre a sua |
| 3 | O `SQL_ABRIR_DLQ` **corre**. Uma base falsa compara SQL por texto e nunca o interpreta: um `::jsonb` em falta, uma coluna com outro nome, um `%s` fora de ordem — nada disso o *gate* 4 ve |
| 4 | O `SQL_CONVERSA_DO_CONTACTO` corre, e a **RLS** esconde a conversa de A do contexto de B (ISO-43..46). A politica e da base; o codigo nao a pode provar |

As cadeias importam-se de `kamba_agr.eventos.consultas`, que e o que a aplicacao
envia — nao copias delas. E a licao do `tests_ten/base.py`: quando a suite
escreve o seu proprio SQL, o SQL da biblioteca **nunca corre contra uma base**.

**O que esta suite nao prova**, e fica dito: o BullMQ. As garantias de entrega
dele sao NAO VERIFICADAS (L6, R9 do epic) e nao ha fila nenhuma aqui — o que
cobre o risco sao *handlers* idempotentes, a DLQ e o reprocessamento, e e isso
que se mede.
"""

from __future__ import annotations

import json
import sys
import threading
import unittest
import uuid
from pathlib import Path

import ligacao
from tests import factories
from tests_agr.base import ComAgr

_RAIZ = Path(__file__).resolve().parents[2]
for _caminho in (
    _RAIZ / "libs" / "py-core" / "src",
    _RAIZ / "services" / "agr" / "src",
):
    if str(_caminho) not in sys.path:
        sys.path.insert(0, str(_caminho))

from kamba_agr.eventos.consultas import (  # noqa: E402
    SQL_ABRIR_DLQ,
    SQL_CONVERSA_DO_CONTACTO,
)
from kamba_core.eventos.consumo import SQL_MARCAR_CONSUMIDO  # noqa: E402

#: O consumidor do Vendedor. Em constante e nao escrito em cada ensaio: e a
#: primeira metade da chave das duas tabelas, e um nome diferente por engano
#: fazia dois ensaios medirem consumidores diferentes sem dar erro.
CONSUMIDOR = "agr_vendedor"


#: **As ligacoes desta suite NAO estao em `autocommit`, e a razao e a RLS.**
#:
#: O `factories.contexto` faz `set_config('app.tenant_id', %s, true)` — com
#: `is_local = true`, como o `tenant_guard` —, e isso vale **so para a
#: transaccao corrente**. Em `autocommit` cada instrucao e a sua propria
#: transaccao: o contexto morre antes do `INSERT` seguinte, e as tres tabelas
#: deste ticket tem `FORCE` com a politica `tenant_iso`, pelo que o `INSERT`
#: falha com `42501 — new row violates row-level security policy`.
#:
#: A primeira versao desta suite punha `autocommit = True` (copiado do
#: `ligacao_de_tranca`, que so corre `pg_advisory_*` e nao toca em RLS) e **as
#: dez escritas falharam todas**. Fica escrito porque e a mesma armadilha que o
#: `consumo.py` do KAM-006 nomeia por extenso: «com `is_local`, morre no
#: `COMMIT`».


class ComEventos(ComAgr):
    """Sementes e limpeza das duas tabelas de eventos.

    **Esta suite confirma o que escreve, contra a convencao do `ComBase`**
    («ligacao que nunca faz `commit`: cada teste desfaz o que escreveu»), e a
    razao e o que ela existe para medir: o `ON CONFLICT` entre **sessoes** so
    decide se a primeira transaccao tiver confirmado, e cinco ligacoes a inserir
    dentro de transaccoes abertas medem o bloqueio e nao a unicidade. Por isso a
    limpeza e explicita — o `_limpar_eventos`, pela chave do evento — e corre
    **antes** do `_limpar` da classe de cima, que fecha a ligacao de
    administracao.
    """

    def setUp(self) -> None:
        super().setUp()
        self.addCleanup(self._limpar_eventos)
        self._eventos: list[str] = []

    def _limpar_eventos(self) -> None:
        for event_id in self._eventos:
            for tabela in ("events_consumed", "events_dlq"):
                self.semente.execute(
                    f"DELETE FROM platform.{tabela} WHERE event_id = %s", (event_id,)
                )

    def novo_evento(self) -> str:
        event_id = str(uuid.uuid4())
        self._eventos.append(event_id)
        return event_id

    def marcar(
        self,
        conexao,
        *,
        tenant_id: str,
        event_id: str,
        seq: int = 1,
        confirmar: bool = True,
    ) -> int:
        """O `INSERT ... ON CONFLICT DO NOTHING`. Devolve as linhas escritas.

        O contexto e o `INSERT` na **mesma** transaccao — ver a nota do
        `CONSUMIDOR` —, e o `confirmar` existe para o ensaio que mede o
        `ROLLBACK`: e o unico que precisa de deixar a transaccao aberta.
        """
        cursor = conexao.cursor()
        try:
            factories.contexto(cursor, tenant_id)
            cursor.execute(
                SQL_MARCAR_CONSUMIDO,
                (CONSUMIDOR, event_id, tenant_id, "order", event_id, seq),
            )
            linhas = cursor.rowcount
        finally:
            cursor.close()
        if confirmar:
            conexao.commit()
        return linhas

    def abrir_dlq(
        self,
        conexao,
        *,
        tenant_id: str,
        event_id: str,
        erro: str = "versao_desconhecida",
        tentativas: int = 1,
    ) -> int:
        cursor = conexao.cursor()
        try:
            factories.contexto(cursor, tenant_id)
            cursor.execute(
                SQL_ABRIR_DLQ,
                (
                    CONSUMIDOR,
                    event_id,
                    "payment.confirmed",
                    1,
                    tenant_id,
                    json.dumps({"id": event_id, "tipo": "payment.confirmed"}),
                    erro,
                    tentativas,
                ),
            )
            linhas = cursor.rowcount
        finally:
            cursor.close()
        conexao.commit()
        return linhas

    def contar(self, tabela: str, event_id: str) -> int:
        self.semente.execute(
            f"SELECT count(*) FROM platform.{tabela} WHERE event_id = %s", (event_id,)
        )
        return int(self.semente.fetchone()[0])


class TestAMarcaEIdempotente(ComEventos):
    """Criterio 2: a mesma entrega duas vezes da **uma** linha."""

    def test_a_segunda_marca_escreve_zero_linhas(self) -> None:
        conversa = self.criar_conversa()
        evento = self.novo_evento()
        conexao = self.ligar("app")
        self.assertEqual(
            self.marcar(conexao, tenant_id=conversa.tenant_id, event_id=evento), 1
        )
        self.assertEqual(
            self.marcar(conexao, tenant_id=conversa.tenant_id, event_id=evento), 0
        )
        self.assertEqual(self.contar("events_consumed", evento), 1)

    def test_a_consulta_corre_de_verdade(self) -> None:
        # O que esta suite existe para dizer: o texto que a aplicacao envia e
        # SQL valido contra este esquema.
        conversa = self.criar_conversa()
        evento = self.novo_evento()
        conexao = self.ligar("app")
        self.assertEqual(
            self.marcar(conexao, tenant_id=conversa.tenant_id, event_id=evento), 1
        )

    def test_cinco_sessoes_em_paralelo_dao_uma_linha(self) -> None:
        """**E aqui que o criterio 2 se prova.**

        Cinco **ligacoes** — nao cinco corrotinas — a correr o mesmo `INSERT`
        ao mesmo tempo. O que decide e o indice unico do servidor, e nao ha
        duplo que o simule: uma base falsa com um trinco mede o trinco dela.
        """
        conversa = self.criar_conversa()
        evento = self.novo_evento()
        barreira = threading.Barrier(5)
        escritas: list[int] = []
        trinco = threading.Lock()

        def entregar() -> None:
            conexao = ligacao.ligar("app")
            try:
                barreira.wait(timeout=30)
                linhas = self.marcar(
                    conexao, tenant_id=conversa.tenant_id, event_id=evento
                )
                with trinco:
                    escritas.append(linhas)
            finally:
                conexao.close()

        fios = [threading.Thread(target=entregar) for _ in range(5)]
        for fio in fios:
            fio.start()
        for fio in fios:
            fio.join(timeout=60)
        self.assertEqual(sorted(escritas), [0, 0, 0, 0, 1])
        self.assertEqual(self.contar("events_consumed", evento), 1)


class TestAMarcaEOEfeitoNaMesmaTransaccao(ComEventos):
    """Criterio 2: sem efeito, sem marca."""

    def test_o_rollback_leva_a_marca_com_ele(self) -> None:
        conversa = self.criar_conversa()
        evento = self.novo_evento()
        conexao = self.ligar("app")
        self.assertEqual(
            self.marcar(
                conexao,
                tenant_id=conversa.tenant_id,
                event_id=evento,
                confirmar=False,
            ),
            1,
        )
        conexao.rollback()
        self.assertEqual(self.contar("events_consumed", evento), 0)

    def test_depois_do_rollback_a_entrega_seguinte_escreve(self) -> None:
        """E o que torna a re-entrega segura: a marca desapareceu com o efeito."""
        conversa = self.criar_conversa()
        evento = self.novo_evento()
        conexao = self.ligar("app")
        self.marcar(
            conexao, tenant_id=conversa.tenant_id, event_id=evento, confirmar=False
        )
        conexao.rollback()
        self.assertEqual(
            self.marcar(conexao, tenant_id=conversa.tenant_id, event_id=evento), 1
        )
        self.assertEqual(self.contar("events_consumed", evento), 1)


class TestADlqAbreEReentra(ComEventos):
    """Criterio 3: a entrada abre, e a reentrada nao abre uma segunda."""

    def test_a_entrada_abre_e_o_sql_corre(self) -> None:
        conversa = self.criar_conversa()
        evento = self.novo_evento()
        conexao = self.ligar("app")
        self.assertEqual(
            self.abrir_dlq(conexao, tenant_id=conversa.tenant_id, event_id=evento), 1
        )
        self.assertEqual(self.contar("events_dlq", evento), 1)

    def test_a_segunda_entrada_aberta_nao_escreve(self) -> None:
        conversa = self.criar_conversa()
        evento = self.novo_evento()
        conexao = self.ligar("app")
        self.abrir_dlq(conexao, tenant_id=conversa.tenant_id, event_id=evento)
        self.assertEqual(
            self.abrir_dlq(conexao, tenant_id=conversa.tenant_id, event_id=evento), 0
        )
        self.assertEqual(self.contar("events_dlq", evento), 1)

    def test_um_ciclo_novo_depois_de_resolvida_abre_a_sua(self) -> None:
        """A unicidade e **parcial**: so entre as abertas (revisao `0005`).

        Sem isto ficava uma DLQ com zero entradas abertas sobre um efeito por
        aplicar — `evt_dlq_open` a zero, alerta nenhum, e a retencao a apagar a
        unica evidencia.
        """
        conversa = self.criar_conversa()
        evento = self.novo_evento()
        conexao = self.ligar("app")
        self.abrir_dlq(conexao, tenant_id=conversa.tenant_id, event_id=evento)
        # Fechar e do `kamba_batch` (revisao `0005`); aqui usa-se o
        # administrador porque o que se mede e o indice e nao o privilegio.
        self.semente.execute(
            "UPDATE platform.events_dlq SET estado = 'reprocessada', "
            "resolvido_at = now(), resolvido_por = 'ensaio' WHERE event_id = %s",
            (evento,),
        )
        self.assertEqual(
            self.abrir_dlq(conexao, tenant_id=conversa.tenant_id, event_id=evento), 1
        )
        self.assertEqual(self.contar("events_dlq", evento), 2)

    def test_o_envelope_entra_como_jsonb(self) -> None:
        """O `::jsonb` do SQL: sem ele, a coluna recusa o texto."""
        conversa = self.criar_conversa()
        evento = self.novo_evento()
        conexao = self.ligar("app")
        self.abrir_dlq(conexao, tenant_id=conversa.tenant_id, event_id=evento)
        self.semente.execute(
            "SELECT envelope->>'tipo' FROM platform.events_dlq WHERE event_id = %s",
            (evento,),
        )
        self.assertEqual(self.semente.fetchone()[0], "payment.confirmed")


class TestAConversaDoContacto(ComEventos):
    """Criterios 4 e 5: a consulta corre, e a RLS isola."""

    def _ler(self, conexao, *, tenant_id: str, contact_id: str, como: str | None = None):
        cursor = conexao.cursor()
        try:
            factories.contexto(cursor, tenant_id if como is None else como)
            cursor.execute(SQL_CONVERSA_DO_CONTACTO, (tenant_id, contact_id))
            return cursor.fetchone()
        finally:
            cursor.close()

    def test_a_consulta_corre_e_devolve_a_conversa(self) -> None:
        conversa = self.criar_conversa()
        conexao = self.ligar("app")
        linha = self._ler(
            conexao, tenant_id=conversa.tenant_id, contact_id=conversa.contact_id
        )
        self.assertIsNotNone(linha)
        self.assertEqual(str(linha[0]), conversa.conversation_id)
        self.assertEqual(str(linha[1]), "bot")
        self.assertFalse(linha[2])

    def test_um_handoff_a_espera_aparece(self) -> None:
        conversa = self.criar_conversa()
        self.abrir_handoff(conversa)
        conexao = self.ligar("app")
        linha = self._ler(
            conexao, tenant_id=conversa.tenant_id, contact_id=conversa.contact_id
        )
        self.assertTrue(linha[2])

    def test_um_modo_que_nao_e_bot_aparece(self) -> None:
        conversa = self.criar_conversa(modo="pausada")
        conexao = self.ligar("app")
        linha = self._ler(
            conexao, tenant_id=conversa.tenant_id, contact_id=conversa.contact_id
        )
        self.assertEqual(str(linha[1]), "pausada")

    def test_o_envelope_forjado_nao_ve_a_conversa_do_outro(self) -> None:
        """**E aqui que o criterio 4 se prova.** ISO-43..46, X-02.

        O contexto e o `tenant_id` do envelope; com um forjado, a RLS nao mostra
        a conversa do *tenant* a que o agregado pertence — e o efeito nunca lhe
        chega.
        """
        conversa = self.criar_conversa()
        outro = self.criar_conversa()
        conexao = self.ligar("app")
        linha = self._ler(
            conexao,
            tenant_id=conversa.tenant_id,
            contact_id=conversa.contact_id,
            como=outro.tenant_id,
        )
        self.assertIsNone(linha)

    def test_duas_conversas_do_mesmo_contacto_escolhem_a_mais_recente(self) -> None:
        """A `0009` e `UNIQUE (tenant_id, contact_id, channel_id)`: o mesmo
        contacto em dois canais tem duas conversas, e o evento traz so o
        contacto."""
        conversa = self.criar_conversa()
        outro_canal = factories.canal(self.semente, conversa.tenant_id)
        recente = str(uuid.uuid4())
        self.semente.execute(
            "INSERT INTO platform.conversations "
            "(id, tenant_id, contact_id, channel_id, mode, last_inbound_at, "
            " window_expires_at) VALUES (%s, %s, %s, %s, 'bot', now() + "
            " interval '1 hour', now() + interval '25 hours')",
            (recente, conversa.tenant_id, conversa.contact_id, outro_canal),
        )
        factories.contexto(self.semente, None)
        conexao = self.ligar("app")
        linha = self._ler(
            conexao, tenant_id=conversa.tenant_id, contact_id=conversa.contact_id
        )
        self.assertEqual(str(linha[0]), recente)


class TestOsPrivilegios(ComEventos):
    """O `kamba_app` escreve nas duas tabelas e **nao** fecha a DLQ."""

    def test_o_app_nao_pode_fechar_uma_entrada_da_dlq(self) -> None:
        """Fechar exige dois aprovadores e e do `kamba_batch` (revisao `0005`).

        E o que torna a entrada do `tool_schema` suficiente com **so** o
        `insert`: nao ha `UPDATE` para o AGR escrever, mesmo que alguem o
        escrevesse.
        """
        conversa = self.criar_conversa()
        evento = self.novo_evento()
        conexao = self.ligar("app")
        self.abrir_dlq(conexao, tenant_id=conversa.tenant_id, event_id=evento)
        cursor = conexao.cursor()
        try:
            factories.contexto(cursor, conversa.tenant_id)
            with self.assertRaises(Exception):
                cursor.execute(
                    "UPDATE platform.events_dlq SET estado = 'descartada' "
                    "WHERE event_id = %s",
                    (evento,),
                )
        finally:
            cursor.close()


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
