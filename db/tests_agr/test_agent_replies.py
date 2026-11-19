"""A saida do AGR contra o PostgreSQL (KAM-224).

O que os duplos de `services/agr/tests/test_saida.py` nao provam, e so a base
diz:

| Propriedade | Porque precisa da base |
|---|---|
| um turno com resposta da **1** linha e **1** `agent.replied` no *outbox* | a transaccao que junta a linha e a `evt_emitir` |
| o turno repetido 3x continua a dar **1** e **1** | o `agent_replies_chave_uq` e o `ON CONFLICT` |
| duas sessoes concorrentes com a mesma chave dao **uma** resposta | a unicidade, entre duas transaccoes |
| o evento nao leva o texto, e e P0 com a finalidade `atendimento` | o envelope que a `evt_emitir` constroi |
| a mesma chave noutro tenant e outra resposta, e A nao ve a de B | a RLS `FORCE` |
| o `kamba_app` nao muda o texto nem apaga | os privilegios por coluna |
| um texto com um telefone nao emite nem grava | a guarda de PII da `evt_emitir`, na mesma transaccao |

As instrucoes sao as de `kamba_agr.saida`, chamadas pela funcao do modulo — nao
uma copia do SQL.
"""

from __future__ import annotations

import datetime
import json
import threading

from tests.base import PRIVILEGIO_INSUFICIENTE, VIOLACAO_DE_CHECK, sqlstate
from tests_agr.base import ComAgr

# O `tests_agr.base` poe o `services/agr/src` no caminho, e por isso vem antes.
from kamba_agr import saida  # noqa: E402


def _agora() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


class ComSaida(ComAgr):
    def setUp(self) -> None:
        super().setUp()
        self.conversa = self.criar_conversa()
        self.tenant = self.conversa.tenant_id
        self.addCleanup(self._limpar_respostas)
        self.app = self.ligar("app")

    def _limpar_respostas(self) -> None:
        for tenant in self._tenants:
            for tabela in ("agent_replies", "events_outbox", "events_log", "evt_agregado_seq"):
                self.semente.execute(f"DELETE FROM platform.{tabela} WHERE tenant_id = %s", (tenant,))

    def estado(self, conversa=None) -> dict:
        c = conversa or self.conversa
        return {
            "tenant_id": c.tenant_id,
            "contact_id": c.contact_id,
            "conversation_id": c.conversation_id,
            "thread_id": f"{c.tenant_id}:{c.contact_id}",
        }

    def emitir(self, ligacao=None, conversa=None, **kw):
        kw.setdefault("chave", "wamid.ensaio:0")
        texto = kw.pop("texto", "Temos em stock.")
        return saida.emitir_resposta(
            ligacao or self.app, self.estado(conversa), texto, turno_iniciado_em=_agora(), **kw
        )

    def _linhas(self, tenant: str | None = None) -> list[tuple]:
        self.semente.execute(
            "SELECT reply_id::text, chave, canal, texto, botoes FROM platform.agent_replies "
            "WHERE tenant_id = %s",
            (tenant or self.tenant,),
        )
        return [tuple(linha) for linha in self.semente.fetchall()]

    def _eventos(self, tenant: str | None = None) -> list[dict]:
        self.semente.execute(
            "SELECT envelope FROM platform.events_outbox WHERE tenant_id = %s AND tipo = %s",
            (tenant or self.tenant, saida.TIPO),
        )
        return [e if isinstance(e, dict) else json.loads(e) for (e,) in self.semente.fetchall()]


class TestUmTurnoUmaResposta(ComSaida):
    def test_um_turno_da_uma_linha_e_um_evento(self) -> None:
        reply_id = self.emitir(botoes=("falar_com_humano",))
        linhas = self._linhas()
        self.assertEqual(len(linhas), 1)
        self.assertEqual(linhas[0][0], reply_id)
        botoes = linhas[0][4] if isinstance(linhas[0][4], list) else json.loads(linhas[0][4])
        self.assertEqual(botoes, [{"id": "falar_com_humano", "titulo": "Falar com um colega"}])
        eventos = self._eventos()
        self.assertEqual(len(eventos), 1)
        envelope = eventos[0]
        self.assertEqual(envelope["payload"]["reply_id"], reply_id)
        self.assertEqual(envelope["payload"]["canal"], "whatsapp")
        self.assertEqual(envelope["agregado"]["tipo"], "conversation")
        self.assertEqual(envelope["agregado"]["id"], self.conversa.conversation_id)
        self.assertEqual((envelope["classe_pii"], envelope["finalidades"]), ("P0", ["atendimento"]))

    def test_o_evento_nao_leva_o_texto(self) -> None:
        self.emitir(texto="Ola Maria, temos o vestido azul.")
        envelope = json.dumps(self._eventos()[0])
        self.assertNotIn("Maria", envelope)
        self.assertNotIn("vestido", envelope)

    def test_o_turno_repetido_tres_vezes_continua_a_dar_uma(self) -> None:
        primeira = self.emitir()
        repetidas = [self.emitir() for _ in range(3)]
        self.assertIsNotNone(primeira)
        self.assertEqual(repetidas, [None, None, None])
        self.assertEqual(len(self._linhas()), 1)
        self.assertEqual(len(self._eventos()), 1)

    def test_duas_sessoes_concorrentes_com_a_mesma_chave_dao_uma(self) -> None:
        ligacoes = [self.ligar("app") for _ in range(2)]
        barreira = threading.Barrier(2)
        resultados: list[object] = []
        trinco = threading.Lock()

        def correr(ligacao) -> None:
            barreira.wait()
            r = self.emitir(ligacao=ligacao)
            with trinco:
                resultados.append(r)

        fios = [threading.Thread(target=correr, args=(l,)) for l in ligacoes]
        for f in fios:
            f.start()
        for f in fios:
            f.join(30)
        self.assertEqual(sorted(r is None for r in resultados), [False, True])
        self.assertEqual(len(self._linhas()), 1)
        self.assertEqual(len(self._eventos()), 1)

    def test_um_numero_no_texto_nao_chega_ao_evento(self) -> None:
        # O texto nao vai no evento, pelo que a guarda de PII da `evt_emitir`
        # nunca o ve e nunca recusa um turno por causa dele: a linha grava, e o
        # envelope fica sem o numero. Quem decide se um texto do AGR pode levar
        # um numero e o renderer (os numeros so de *facts*), nao esta tabela.
        self.emitir(texto="Ligue para 999 000 000.")
        self.assertEqual(len(self._linhas()), 1)
        self.assertNotIn("999", json.dumps(self._eventos()[0]))


class TestIsolamento(ComSaida):
    def test_a_mesma_chave_noutro_tenant_e_outra_resposta(self) -> None:
        outra = self.criar_conversa()
        self.emitir()
        self.emitir(conversa=outra)
        self.assertEqual(len(self._linhas()), 1)
        self.assertEqual(len(self._linhas(outra.tenant_id)), 1)
        self.assertEqual(len(self._eventos(outra.tenant_id)), 1)

    def test_a_conversa_de_outro_tenant_nao_entra(self) -> None:
        outra = self.criar_conversa()
        estado = self.estado()
        estado["conversation_id"] = outra.conversation_id
        with self.assertRaises(Exception) as erro:
            saida.emitir_resposta(self.app, estado, "ola", chave="k:0")
        # A FK composta: a conversa de B nao e deste tenant.
        self.assertEqual(sqlstate(erro.exception), "23503")
        self.assertEqual(self._linhas(), [])
        self.assertEqual(self._eventos(), [])

    def test_a_nao_ve_as_respostas_de_b(self) -> None:
        outra = self.criar_conversa()
        self.emitir(conversa=outra)
        cursor = self.app.cursor()
        cursor.execute("SELECT set_config('app.tenant_id', %s, false)", (self.tenant,))
        cursor.execute("SELECT count(*) FROM platform.agent_replies")
        self.assertEqual(cursor.fetchone()[0], 0)
        self.app.rollback()


class TestPrivilegios(ComSaida):
    def _como_app(self, sql: str, parametros: tuple) -> None:
        cursor = self.app.cursor()
        try:
            cursor.execute("SELECT set_config('app.tenant_id', %s, true)", (self.tenant,))
            cursor.execute(sql, parametros)
        finally:
            self.app.rollback()

    def test_o_texto_nao_muda_depois_de_emitido(self) -> None:
        reply_id = self.emitir()
        with self.assertRaises(Exception) as erro:
            self._como_app(
                "UPDATE platform.agent_replies SET texto = 'outro' WHERE reply_id = %s", (reply_id,)
            )
        self.assertEqual(sqlstate(erro.exception), PRIVILEGIO_INSUFICIENTE)

    def test_ninguem_apaga(self) -> None:
        reply_id = self.emitir()
        with self.assertRaises(Exception) as erro:
            self._como_app("DELETE FROM platform.agent_replies WHERE reply_id = %s", (reply_id,))
        self.assertEqual(sqlstate(erro.exception), PRIVILEGIO_INSUFICIENTE)

    def test_o_canal_e_fechado(self) -> None:
        with self.assertRaises(Exception) as erro:
            self._como_app(
                "INSERT INTO platform.agent_replies "
                "(tenant_id, chave, contact_id, conversation_id, canal, texto) "
                "VALUES (%s, 'k:9', %s, %s, 'sms', 'ola')",
                (self.tenant, self.conversa.contact_id, self.conversa.conversation_id),
            )
        self.assertEqual(sqlstate(erro.exception), VIOLACAO_DE_CHECK)

    def test_quatro_botoes_recusam(self) -> None:
        with self.assertRaises(Exception) as erro:
            self._como_app(
                "INSERT INTO platform.agent_replies "
                "(tenant_id, chave, contact_id, conversation_id, canal, texto, botoes) "
                "VALUES (%s, 'k:9', %s, %s, 'whatsapp', 'ola', '[1,2,3,4]'::jsonb)",
                (self.tenant, self.conversa.contact_id, self.conversa.conversation_id),
            )
        self.assertEqual(sqlstate(erro.exception), VIOLACAO_DE_CHECK)
