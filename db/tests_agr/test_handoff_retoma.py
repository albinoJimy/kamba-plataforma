"""O *compare-and-set* da retoma, contra a base (KAM-034, criterios 3, 7 e 8).

As cinco cadeias sao as do `kamba_agr.consultas`, importadas — nao copias delas.
E a licao que o `tests_ten/base.py` escreveu e que o `test_palavra.py` repetiu:
uma base falsa compara SQL por texto e nunca o interpreta, pelo que um erro de
sintaxe, uma coluna com outro nome ou um `%s` fora de ordem dao uma resposta
plausivel e passam o *gate* 4 inteiro.

O que **so** esta suite pode dizer, e e por isso que existe ao lado da bateria
de unidade do AGR:

| Propriedade | Porque e que precisa da base |
|---|---|
| o CAS e atomico entre sessoes | duas ligacoes a correr o mesmo `UPDATE` sobre a mesma linha: so a base as serializa, e e isso que faz do *webhook* duplicado um *no-op* |
| a RLS esconde a passagem de outro *tenant* | a politica e da base; o codigo nao a pode provar |
| o vinculo ao *thread* pelo `contact_id` | o `EXISTS` sobre `conversations` corre; um duplo que o ignore afirma o contrario |
| o `GRANT UPDATE` por coluna | a `0011` da `status`, `external_id`, `resumed_at` e `resolver` e mais nada — e um `UPDATE` de outra coluna tem de ser recusado **pela base** |
| a varredura das 24 h sobre `timestamptz` | o `opened_at` e o relogio do servidor, e comparar um `datetime` sem fuso com ele dependia do `TimeZone` da sessao |
"""

from __future__ import annotations

import datetime as dt
import unittest
import uuid

from tests import factories
from tests_agr.base import (
    SQL_HANDOFF_PARA_RETOMA,
    SQL_HANDOFFS_EXPIRADOS,
    SQL_PASSAGENS_A_ESPERA,
    SQL_RETOMAR_HANDOFF,
    SQL_REVERTER_RETOMA,
    SQL_SLA_DE_RETOMA,
    ComAgr,
)


class _ComRetoma(ComAgr):
    """Correr as cadeias da retoma com contexto de *tenant*, como a aplicacao."""

    def cas(self, conexao, conversa, handoff_id, estado_novo, *, como=None, contacto=None):
        """O `SQL_RETOMAR_HANDOFF`. Devolve `True` se casou uma linha."""
        tenant = conversa.tenant_id if como is None else como
        cursor = conexao.cursor()
        try:
            factories.contexto(cursor, tenant)
            cursor.execute(
                SQL_RETOMAR_HANDOFF,
                (
                    estado_novo,
                    tenant,
                    handoff_id,
                    conversa.contact_id if contacto is None else contacto,
                ),
            )
            venceu = cursor.fetchone() is not None
            # **Confirma**, como o `tool_audit` faz: o `linha_crua` le pela
            # ligacao do administrador, e uma escrita por confirmar e invisivel
            # a outra ligacao — a suite ficava verde a afirmar sobre o nada.
            conexao.commit()
            return venceu
        finally:
            cursor.close()

    def estado(self, conexao, conversa, handoff_id, *, como=None, contacto=None):
        """O `SQL_HANDOFF_PARA_RETOMA`. Devolve o `status` ou `None`."""
        tenant = conversa.tenant_id if como is None else como
        cursor = conexao.cursor()
        try:
            factories.contexto(cursor, tenant)
            cursor.execute(
                SQL_HANDOFF_PARA_RETOMA,
                (
                    tenant,
                    handoff_id,
                    conversa.contact_id if contacto is None else contacto,
                ),
            )
            linha = cursor.fetchone()
            return None if linha is None else str(linha[0])
        finally:
            cursor.close()

    def reverter(self, conexao, conversa, handoff_id, estado):
        cursor = conexao.cursor()
        try:
            factories.contexto(cursor, conversa.tenant_id)
            cursor.execute(
                SQL_REVERTER_RETOMA, (conversa.tenant_id, handoff_id, estado)
            )
            revertida = cursor.fetchone() is not None
            conexao.commit()
            return revertida
        finally:
            cursor.close()

    def linha_crua(self, handoff_id):
        """A linha pelo administrador, para ler o que a RLS esconderia."""
        self.semente.execute(
            "SELECT status, opened_at, resumed_at, resolver "
            "  FROM platform.handoffs WHERE handoff_id = %s",
            (handoff_id,),
        )
        return self.semente.fetchone()


class TestOCompareAndSet(_ComRetoma):
    def test_a_primeira_retoma_vence_e_escreve_o_instante(self) -> None:
        conversa = self.criar_conversa()
        handoff = self.abrir_handoff(conversa)
        conexao = self.ligar("app")
        self.assertTrue(self.cas(conexao, conversa, handoff, "resumed"))
        estado, aberta, retomada, resolver = self.linha_crua(handoff)
        self.assertEqual(estado, "resumed")
        self.assertIsNotNone(retomada)
        self.assertGreaterEqual(retomada, aberta)
        # **O `resolver` nao se escreve aqui.** O corpo da retoma tem tres
        # campos e nenhum e o agente; quem sabe quem respondeu e o HND, pelo seu
        # proprio `close` (§3.15, e o ADR-010 pelo outro lado).
        self.assertIsNone(resolver)

    def test_o_segundo_pedido_nao_casa_linha_nenhuma(self) -> None:
        """O *webhook* duplicado do Chatwoot: *no-op* **pela base**."""
        conversa = self.criar_conversa()
        handoff = self.abrir_handoff(conversa)
        conexao = self.ligar("app")
        self.assertTrue(self.cas(conexao, conversa, handoff, "resumed"))
        antes = self.linha_crua(handoff)[2]
        self.assertFalse(self.cas(conexao, conversa, handoff, "resumed"))
        # E nao reescreve o `resumed_at`: o segundo nao vence, logo nao toca.
        self.assertEqual(self.linha_crua(handoff)[2], antes)

    def test_duas_sessoes_concorrentes_dao_uma_retoma(self) -> None:
        """Criterio 3, e e isto que **so** a base pode dizer.

        Duas ligacoes, o mesmo `handoff_id`, o mesmo `UPDATE`. A serializacao e
        do PostgreSQL: a segunda espera pela linha, re-avalia o predicado com o
        estado **novo**, e nao casa. Com duas replicas do HND a receber o mesmo
        *callback*, e esta a unica barreira que ha.
        """
        conversa = self.criar_conversa()
        handoff = self.abrir_handoff(conversa)
        uma, outra = self.ligar("app"), self.ligar("app")
        venceram = [
            self.cas(uma, conversa, handoff, "resumed"),
            self.cas(outra, conversa, handoff, "resumed"),
        ]
        self.assertEqual(venceram.count(True), 1, venceram)

    def test_nao_se_retoma_de_um_estado_que_nao_e_waiting(self) -> None:
        """Os quatro estados terminais nao voltam atras.

        Sem o `status = 'waiting'` no predicado, um `resolved` duplicado
        encontrava a passagem em `resumed` e **vencia outra vez** — que e o que
        o *no-op* existe para impedir.
        """
        for estado in ("resumed", "timeout", "cancelled", "degraded"):
            with self.subTest(estado=estado):
                conversa = self.criar_conversa()
                handoff = self.abrir_handoff(conversa, estado=estado)
                conexao = self.ligar("app")
                self.assertFalse(self.cas(conexao, conversa, handoff, "resumed"))
                self.assertEqual(self.linha_crua(handoff)[0], estado)

    def test_os_tres_estados_novos_escrevem_se(self) -> None:
        """O controlo positivo: `resumed`, `timeout` e `cancelled` passam o `CHECK`."""
        for estado in ("resumed", "timeout", "cancelled"):
            with self.subTest(estado=estado):
                conversa = self.criar_conversa()
                handoff = self.abrir_handoff(conversa)
                conexao = self.ligar("app")
                self.assertTrue(self.cas(conexao, conversa, handoff, estado))
                self.assertEqual(self.linha_crua(handoff)[0], estado)


class TestOVinculoAoThread(_ComRetoma):
    def test_a_passagem_de_outro_contacto_do_mesmo_tenant_nao_retoma(self) -> None:
        """**O defeito que o `handoff_id` sozinho nao impede.**

        Ele e `sha256(thread_id:handoff_seq)` e portanto irreversivel: do
        identificador nao se le o *thread* de volta. Com so o `tenant_id` no
        predicado, um `handoff_id` do mesmo *tenant* e de outro contacto
        retomava — e o `Command(resume=...)` ia ao *thread* errado, isto e, a
        conversa de outra pessoa com o desfecho desta.
        """
        conversa = self.criar_conversa()
        handoff = self.abrir_handoff(conversa)
        outro_contacto = factories.contacto(self.semente, conversa.tenant_id)
        factories.contexto(self.semente, None)
        conexao = self.ligar("app")
        self.assertFalse(
            self.cas(conexao, conversa, handoff, "resumed", contacto=outro_contacto)
        )
        self.assertEqual(self.linha_crua(handoff)[0], "waiting")
        # E o controlo positivo, com o contacto certo.
        self.assertTrue(self.cas(conexao, conversa, handoff, "resumed"))

    def test_a_leitura_de_classificacao_separa_o_duplicado_da_recusa(self) -> None:
        conversa = self.criar_conversa()
        handoff = self.abrir_handoff(conversa)
        conexao = self.ligar("app")
        # Deste *thread* e a espera: retomavel.
        self.assertEqual(self.estado(conexao, conversa, handoff), "waiting")
        self.assertTrue(self.cas(conexao, conversa, handoff, "resumed"))
        # Deste *thread* e ja retomada: duplicado, 200 sem efeito.
        self.assertEqual(self.estado(conexao, conversa, handoff), "resumed")
        # De outro contacto: nao e deste *thread*, logo recusa.
        outro = factories.contacto(self.semente, conversa.tenant_id)
        factories.contexto(self.semente, None)
        self.assertIsNone(self.estado(conexao, conversa, handoff, contacto=outro))
        # E uma que nao existe.
        self.assertIsNone(self.estado(conexao, conversa, f"h-{uuid.uuid4().hex}"))


class TestOIsolamento(_ComRetoma):
    def test_a_passagem_de_outro_tenant_nao_se_retoma_nem_se_le(self) -> None:
        """O DoD: «`resume` valida `tenant_id` do `thread_id` e do `handoff`».

        A primeira barreira e a RLS, que esconde a linha do contexto de B; a
        segunda e o `tenant_id` no predicado, que torna a instrucao correcta
        mesmo corrida sem contexto. As duas sao da base, e e por isso que isto
        se mede aqui.
        """
        de_a = self.criar_conversa()
        de_b = self.criar_conversa()
        handoff = self.abrir_handoff(de_a)
        conexao = self.ligar("app")
        # O contexto e de B e a passagem e de A: nao casa e nao se le.
        self.assertFalse(self.cas(conexao, de_a, handoff, "resumed", como=de_b.tenant_id))
        self.assertIsNone(self.estado(conexao, de_a, handoff, como=de_b.tenant_id))
        self.assertEqual(self.linha_crua(handoff)[0], "waiting")

    def test_a_aplicacao_nao_pode_escrever_as_colunas_que_nao_lhe_deram(self) -> None:
        """O `GRANT UPDATE` por coluna da `0011`, e nao uma regra do codigo.

        Quatro colunas: `status`, `external_id`, `resumed_at` e `resolver`. O
        `handoff_id`, o `tenant_id`, o `conversation_id`, o `motivo` e o
        `opened_at` ficam de fora — «mudar o motivo depois de alguem ter sido
        chamado e reescrever porque e que foi».
        """
        conversa = self.criar_conversa()
        handoff = self.abrir_handoff(conversa)
        conexao = self.ligar("app")
        for coluna, valor in (("motivo", "outro"), ("opened_at", "now()")):
            with self.subTest(coluna=coluna):
                cursor = conexao.cursor()
                try:
                    factories.contexto(cursor, conversa.tenant_id)
                    with self.assertRaises(Exception):
                        cursor.execute(
                            f"UPDATE platform.handoffs SET {coluna} = %s "
                            " WHERE handoff_id = %s",
                            (valor, handoff),
                        )
                    conexao.rollback()
                finally:
                    cursor.close()


class TestACompensacao(_ComRetoma):
    def test_a_reversao_devolve_a_passagem_a_waiting(self) -> None:
        """Sem ela, a passagem ficava em `resumed` com o grafo interrompido —
        invisivel, porque a varredura dos prazos so olha para `waiting`."""
        conversa = self.criar_conversa()
        handoff = self.abrir_handoff(conversa)
        conexao = self.ligar("app")
        self.assertTrue(self.cas(conexao, conversa, handoff, "resumed"))
        self.assertTrue(self.reverter(conexao, conversa, handoff, "resumed"))
        estado, _aberta, retomada, _resolver = self.linha_crua(handoff)
        self.assertEqual(estado, "waiting")
        self.assertIsNone(retomada, "o instante da retoma tambem se apaga")
        # E o CAS volta a vencer.
        self.assertTrue(self.cas(conexao, conversa, handoff, "resumed"))

    def test_a_reversao_so_toca_a_passagem_no_estado_que_este_pedido_escreveu(
        self,
    ) -> None:
        """O predicado, e nao a confianca: so reverte de `resumed` para `waiting`
        se la estiver `resumed`."""
        conversa = self.criar_conversa()
        handoff = self.abrir_handoff(conversa)
        conexao = self.ligar("app")
        self.assertTrue(self.cas(conexao, conversa, handoff, "timeout"))
        self.assertFalse(self.reverter(conexao, conversa, handoff, "resumed"))
        self.assertEqual(self.linha_crua(handoff)[0], "timeout")


class TestAVarreduraDosPrazos(_ComRetoma):
    """Criterio 7, e corre como `kamba_batch` porque atravessa *tenants*."""

    def expiradas(self, limite, tecto=500):
        conexao = self.ligar("batch")
        cursor = conexao.cursor()
        try:
            cursor.execute(SQL_HANDOFFS_EXPIRADOS, (limite, tecto))
            return [
                (str(linha[0]), str(linha[1]), str(linha[2]))
                for linha in cursor.fetchall()
            ]
        finally:
            cursor.close()

    def test_uma_passagem_de_vinte_e_cinco_horas_aparece_e_uma_de_vinte_e_tres_nao(
        self,
    ) -> None:
        conversa = self.criar_conversa()
        velha = self.abrir_handoff(conversa, ha_horas=25)
        nova = self.abrir_handoff(conversa, ha_horas=23)
        limite = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=24)
        achadas = {h for h, _t, _c in self.expiradas(limite)}
        self.assertIn(velha, achadas)
        self.assertNotIn(nova, achadas)

    def test_a_varredura_devolve_o_contacto_para_reconstruir_o_thread(self) -> None:
        """Sem o `contact_id` a varredura sabia **o que** expirou e nao **onde**
        retomar: o `thread_id` e `{tenant_id}:{contact_id}`."""
        conversa = self.criar_conversa()
        handoff = self.abrir_handoff(conversa, ha_horas=30)
        limite = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=24)
        linhas = [linha for linha in self.expiradas(limite) if linha[0] == handoff]
        self.assertEqual(len(linhas), 1)
        self.assertEqual(linhas[0][1], str(conversa.tenant_id))
        self.assertEqual(linhas[0][2], str(conversa.contact_id))

    def test_so_as_waiting_entram_na_varredura(self) -> None:
        """Uma passagem que ja fechou nao se retoma por prazo."""
        conversa = self.criar_conversa()
        fechadas = [
            self.abrir_handoff(conversa, estado=estado, ha_horas=48)
            for estado in ("resumed", "timeout", "cancelled", "degraded")
        ]
        limite = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=24)
        achadas = {h for h, _t, _c in self.expiradas(limite)}
        for handoff in fechadas:
            self.assertNotIn(handoff, achadas)

    def test_a_varredura_atravessa_tenants(self) -> None:
        """E a razao de correr como `kamba_batch`: com contexto de um *tenant*, a
        RLS devolvia so as passagens desse, e a varredura teria de saber a lista
        de *tenants* antes de varrer."""
        de_a = self.criar_conversa()
        de_b = self.criar_conversa()
        handoffs = {
            self.abrir_handoff(de_a, ha_horas=30),
            self.abrir_handoff(de_b, ha_horas=30),
        }
        limite = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=24)
        achadas = {h for h, _t, _c in self.expiradas(limite)}
        self.assertTrue(handoffs <= achadas, handoffs - achadas)

    def test_o_tecto_limita_as_linhas_e_traz_as_mais_antigas(self) -> None:
        """Uma varredura sem tecto, depois de o provedor estar em baixo um fim de
        semana, trazia dezenas de milhares de linhas e falhava — e uma varredura
        que falha nao retoma nenhuma."""
        conversa = self.criar_conversa()
        mais_velha = self.abrir_handoff(conversa, ha_horas=72)
        self.abrir_handoff(conversa, ha_horas=30)
        self.abrir_handoff(conversa, ha_horas=28)
        limite = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=24)
        linhas = self.expiradas(limite, tecto=1)
        self.assertEqual(len(linhas), 1)
        self.assertEqual(linhas[0][0], mais_velha)


class TestODrain(_ComRetoma):
    """O instrumento do *drain* dos Detalhes Tecnicos do bloco."""

    def a_espera(self):
        conexao = self.ligar("batch")
        cursor = conexao.cursor()
        try:
            cursor.execute(SQL_PASSAGENS_A_ESPERA)
            return int(cursor.fetchone()[0])
        finally:
            cursor.close()

    def test_conta_as_waiting_e_nao_as_outras(self) -> None:
        """Uma passagem em `waiting` e um `interrupt()` pendente num
        *checkpoint*; as outras quatro sao passagens **acabadas**, e um *drain*
        que as contasse nunca chegava a zero."""
        conversa = self.criar_conversa()
        antes = self.a_espera()
        self.abrir_handoff(conversa, estado="waiting")
        self.abrir_handoff(conversa, estado="waiting")
        for estado in ("resumed", "timeout", "cancelled", "degraded"):
            self.abrir_handoff(conversa, estado=estado)
        self.assertEqual(self.a_espera(), antes + 2)

    def test_atravessa_tenants(self) -> None:
        """Um *deploy* e global: contar so as do *tenant* do contexto era deixar
        passar as dos outros."""
        de_a = self.criar_conversa()
        de_b = self.criar_conversa()
        antes = self.a_espera()
        self.abrir_handoff(de_a)
        self.abrir_handoff(de_b)
        self.assertEqual(self.a_espera(), antes + 2)

    def test_uma_retoma_desce_a_contagem(self) -> None:
        """O *drain* acaba quando elas saem de `waiting`, e e isso que o
        procedimento do §7-G espera."""
        conversa = self.criar_conversa()
        handoff = self.abrir_handoff(conversa)
        antes = self.a_espera()
        conexao = self.ligar("app")
        self.assertTrue(self.cas(conexao, conversa, handoff, "resumed"))
        self.assertEqual(self.a_espera(), antes - 1)


class TestOSlaDeRetoma(_ComRetoma):
    """Criterio 8: «a metrica de retoma < 15 min e calculavel por *tenant*»."""

    def sla(self, conexao, conversa, intervalo="15 minutes", desde=None):
        """O `SQL_SLA_DE_RETOMA` com contexto de *tenant*.

        **A janela por omissao sao 30 dias e nao 1, e isso foi um defeito
        medido.** Com 24 h, uma passagem que expirou — que por definicao tem
        mais de 24 h — caia **fora da janela**, e o ensaio do `timeout`
        passava sem nunca exercitar o predicado `status = 'resumed'`: a mutacao
        `handoff: o SLA passa a contar tambem as que expiraram` **sobreviveu** a
        primeira medicao. Uma janela que exclui o caso que o ensaio quer medir
        e um ensaio verde sobre o nada.
        """
        if desde is None:
            desde = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=30)
        cursor = conexao.cursor()
        try:
            factories.contexto(cursor, conversa.tenant_id)
            cursor.execute(SQL_SLA_DE_RETOMA, (intervalo, conversa.tenant_id, desde))
            dentro, total = cursor.fetchone()
            return int(dentro), int(total)
        finally:
            cursor.close()

    def test_uma_retoma_rapida_conta_dentro_e_uma_lenta_conta_fora(self) -> None:
        conversa = self.criar_conversa()
        rapida = self.abrir_handoff(conversa, ha_horas=0.1)  # 6 min
        lenta = self.abrir_handoff(conversa, ha_horas=2)
        conexao = self.ligar("app")
        self.assertTrue(self.cas(conexao, conversa, rapida, "resumed"))
        self.assertTrue(self.cas(conexao, conversa, lenta, "resumed"))
        self.assertEqual(self.sla(conexao, conversa), (1, 2))

    def test_um_timeout_nao_entra_no_denominador(self) -> None:
        """Uma passagem que acabou em `timeout` **nao foi atendida**, e po-la no
        denominador de um SLA de atendimento era contar uma falha como amostra.

        **A `resumed` ao lado nao e enfeite: e ela que prova que a janela cobre
        o caso.** Uma expiracao tem sempre mais de 24 h, pelo que um ensaio com
        janela curta excluia-a pelo `opened_at` e dava verde sem o predicado do
        `status` ter sido exercitado — foi assim que a mutação
        `handoff: o SLA passa a contar tambem as que expiraram` sobreviveu a
        primeira medicao. Com as duas da mesma idade, o `total == 1` diz que a
        janela as cobre **as duas** e que o que exclui uma e o estado.
        """
        conversa = self.criar_conversa()
        expirada = self.abrir_handoff(conversa, ha_horas=25)
        lenta = self.abrir_handoff(conversa, ha_horas=26)
        conexao = self.ligar("app")
        self.assertTrue(self.cas(conexao, conversa, expirada, "timeout"))
        self.assertTrue(self.cas(conexao, conversa, lenta, "resumed"))
        self.assertEqual(self.sla(conexao, conversa), (0, 1))

    def test_o_sla_e_por_tenant_e_nao_ve_o_do_outro(self) -> None:
        """E a razao de a metrica ser uma **consulta** e nao uma serie temporal:
        o `tenant_id` nao entra em etiqueta (`OBS-I`), e aqui e uma coluna."""
        de_a = self.criar_conversa()
        de_b = self.criar_conversa()
        rapida_de_a = self.abrir_handoff(de_a, ha_horas=0.1)
        lenta_de_b = self.abrir_handoff(de_b, ha_horas=3)
        conexao = self.ligar("app")
        self.assertTrue(self.cas(conexao, de_a, rapida_de_a, "resumed"))
        self.assertTrue(self.cas(conexao, de_b, lenta_de_b, "resumed"))
        self.assertEqual(self.sla(conexao, de_a), (1, 1))
        self.assertEqual(self.sla(conexao, de_b), (0, 1))

    def test_usa_o_indice_que_a_revisao_0011_criou(self) -> None:
        """O `handoffs_tenant_idx` e `(tenant_id, opened_at DESC)`, e a `0011`
        escolheu a segunda coluna **por causa desta consulta**. Sem o indice, o
        SLA ordenava em memoria."""
        self.semente.execute(
            "SELECT indexdef FROM pg_indexes "
            " WHERE schemaname = 'platform' AND indexname = 'handoffs_tenant_idx'"
        )
        linha = self.semente.fetchone()
        self.assertIsNotNone(linha, "o handoffs_tenant_idx da 0011 desapareceu")
        self.assertIn("tenant_id", linha[0])
        self.assertIn("opened_at", linha[0])


if __name__ == "__main__":
    unittest.main()
