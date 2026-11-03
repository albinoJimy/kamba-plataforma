"""As vinte sessoes do criterio 3: sequencias 1..20 sem lacunas (`FOR UPDATE`).

O que so aqui se prova, e nenhuma base falsa pode: que a tranca e a **da
cobranca** e serializa a contagem. Em serie, `1 + count(*)` da sempre o numero
certo e o ensaio ficava verde sem `FOR UPDATE` nenhum — que e exactamente a
mutacao que esta suite existe para apanhar.

E um passo de canario, que e a parte que torna o resto honesto: sem a tranca,
as vinte sessoes **tem** de colidir. Se nao colidirem, o que o ensaio mede nao e
a tranca.
"""

from __future__ import annotations

import concurrent.futures
import uuid

import ligacao
import pg8000.dbapi
from tests.base import sqlstate
from tests_pagamentos.base import VALOR, ComLedger, _chamada

#: Vinte, como o criterio pede. Uma ligacao por chamada: e a unica forma de as
#: ter a disputar a mesma tranca — na mesma ligacao a segunda tomada e
#: concedida de imediato.
CHAMADAS = 20


def _appendar_noutra_ligacao(tenant: str, cobranca: str, conta: str, tipo: str):
    """Uma chamada a porta, numa ligacao propria, confirmada ou revertida.

    Devolve `(sequencia, None)` ou `(None, sqlstate)`. Nao levanta: o que o
    ensaio quer e a **distribuicao** dos resultados, e uma excepcao a atravessar
    a piscina perdia as outras dezanove.
    """
    conexao = ligacao.ligar("app")
    try:
        cursor = conexao.cursor()
        cursor.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant,))
        cursor.fetchone()
        argumentos = {
            "p_charge_id": cobranca,
            "p_tipo_evento": tipo,
            "p_account_id": conta,
            "p_valor_minor": VALOR,
            "p_authn_method": "hmac",
            "p_authn_ok": True,
            "p_decisao": "informativo",
            "p_motivo": None,
            "p_actor_kind": "provider",
            "p_actor_id": None,
            "p_provider_event_id": f"ev-{uuid.uuid4().hex[:12]}",
            "p_payload": "{}",
            "p_ocorrido_at": None,
        }
        cursor.execute(*_chamada(argumentos))
        sequencia = cursor.fetchone()[1]
        conexao.commit()
        return sequencia, None
    except pg8000.dbapi.DatabaseError as erro:
        conexao.rollback()
        return None, sqlstate(erro)
    finally:
        conexao.close()


class TestSequenciaSobConcorrencia(ComLedger):
    """Criterio 3: vinte chamadas concorrentes dao 1..20 sem lacunas."""

    def setUp(self) -> None:
        super().setUp()
        self.tenant = self.criar_tenant()
        self.conta = self.criar_conta(self.tenant)
        self.cobranca = self.criar_cobranca(self.tenant, self.conta)

    def test_vinte_chamadas_concorrentes_dao_1_a_20(self) -> None:
        with concurrent.futures.ThreadPoolExecutor(max_workers=CHAMADAS) as piscina:
            tarefas = [
                piscina.submit(
                    _appendar_noutra_ligacao,
                    self.tenant,
                    self.cobranca,
                    self.conta,
                    "pagamento_recebido",
                )
                for _ in range(CHAMADAS)
            ]
            resultados = [t.result() for t in concurrent.futures.as_completed(tarefas)]

        sequencias = sorted(s for s, _ in resultados if s is not None)
        falhas = [e for s, e in resultados if s is None]
        self.assertEqual(
            falhas,
            [],
            "nenhuma chamada devia falhar: com a tranca na cobranca elas "
            "esperam-se umas pelas outras em vez de colidirem",
        )
        self.assertEqual(
            sequencias,
            list(range(1, CHAMADAS + 1)),
            "sequencias 1..20 sem lacunas e sem repeticoes",
        )

    def test_duas_sequencias_de_tipos_diferentes_contam_a_parte(self) -> None:
        """A sequencia e por `(provider, conta, referencia, tipo_evento)`.

        Dez `pagamento_recebido` e dez `pagamento_orfao` dao 1..10 duas vezes, e
        nao 1..20 uma vez. Sem isto, um `count(*)` sobre a cobranca inteira —
        que e o erro facil de escrever — passava o ensaio acima.
        """
        with concurrent.futures.ThreadPoolExecutor(max_workers=CHAMADAS) as piscina:
            tarefas = [
                piscina.submit(
                    _appendar_noutra_ligacao,
                    self.tenant,
                    self.cobranca,
                    self.conta,
                    "pagamento_recebido" if n % 2 == 0 else "pagamento_orfao",
                )
                for n in range(CHAMADAS)
            ]
            [t.result() for t in concurrent.futures.as_completed(tarefas)]

        self.semente.execute(
            "SELECT tipo_evento, array_agg(sequencia ORDER BY sequencia) "
            "  FROM platform.payment_events WHERE charge_id = %s "
            " GROUP BY tipo_evento ORDER BY tipo_evento",
            (self.cobranca,),
        )
        por_tipo = {t: list(s) for t, s in self.semente.fetchall()}
        self.assertEqual(
            por_tipo,
            {
                "pagamento_orfao": list(range(1, CHAMADAS // 2 + 1)),
                "pagamento_recebido": list(range(1, CHAMADAS // 2 + 1)),
                # O da semente: a cobranca nasce `iniciada` e chega a `emitida`
                # pela porta.
                "referencia_emitida": [1],
            },
        )

    def test_a_cadeia_de_hashes_sobrevive_a_concorrencia(self) -> None:
        """O `prev_hash` tambem e serializado pela mesma tranca.

        E a parte que se perde se alguem trocar o `FOR UPDATE` por um
        `pg_advisory_lock` sobre o tipo de evento: as sequencias ficavam certas
        e a cadeia partia-se, porque dois eventos liam o mesmo `prev_hash`.
        """
        with concurrent.futures.ThreadPoolExecutor(max_workers=CHAMADAS) as piscina:
            tarefas = [
                piscina.submit(
                    _appendar_noutra_ligacao,
                    self.tenant,
                    self.cobranca,
                    self.conta,
                    "pagamento_recebido",
                )
                for _ in range(CHAMADAS)
            ]
            [t.result() for t in concurrent.futures.as_completed(tarefas)]

        self.semente.execute(
            "SELECT count(*) FROM platform.verify_ledger_chain(%s)", (self.cobranca,)
        )
        self.assertEqual(
            int(self.semente.fetchone()[0]),
            0,
            "nenhum elo partido depois de vinte escritas concorrentes",
        )

    def test_canario_sem_a_tranca_as_vinte_colidem(self) -> None:
        """**A prova de que o que o primeiro ensaio mede e a tranca.**

        Troca o `FOR UPDATE` por um `SELECT` simples numa copia da funcao, corre
        as vinte, e exige que **alguma** falhe — a unicidade
        `payment_events_uq` apanha duas sequencias iguais. Se todas passassem, o
        `FOR UPDATE` nao era o que fazia a diferenca e o criterio ficava por
        provar.

        A copia e uma funcao **com outro nome**, e a original nunca e tocada:
        alterar a funcao de producao a meio de uma suite deixava-a alterada se o
        ensaio morresse.
        """
        self.semente.execute(
            "SELECT pg_get_functiondef(p.oid) FROM pg_proc p "
            "  JOIN pg_namespace n ON n.oid = p.pronamespace "
            " WHERE n.nspname = 'platform' AND p.proname = 'append_payment_event'"
        )
        definicao = self.semente.fetchone()[0]
        self.assertIn(
            "FOR UPDATE",
            definicao,
            "a funcao de producao tem de ter o FOR UPDATE do contrato do §6.2",
        )
        sem_tranca = definicao.replace(
            "platform.append_payment_event", "platform.append_sem_tranca", 1
        ).replace("WHERE id = p_charge_id FOR UPDATE", "WHERE id = p_charge_id", 1)
        self.assertNotIn(
            "FOR UPDATE", sem_tranca, "a copia tem de ficar mesmo sem a tranca"
        )
        self.semente.execute(sem_tranca)
        self.semente.execute(
            "GRANT EXECUTE ON FUNCTION platform.append_sem_tranca("
            "uuid, text, uuid, bigint, text, boolean, text, text, text, uuid, "
            "text, jsonb, timestamp with time zone) TO kamba_app"
        )
        try:
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=CHAMADAS
            ) as piscina:
                tarefas = [
                    piscina.submit(
                        _appendar_sem_tranca,
                        self.tenant,
                        self.cobranca,
                        self.conta,
                    )
                    for _ in range(CHAMADAS)
                ]
                resultados = [
                    t.result() for t in concurrent.futures.as_completed(tarefas)
                ]
        finally:
            self.semente.execute(
                "DROP FUNCTION platform.append_sem_tranca("
                "uuid, text, uuid, bigint, text, boolean, text, text, text, "
                "uuid, text, jsonb, timestamp with time zone)"
            )

        falhas = [e for s, e in resultados if s is None]
        self.assertNotEqual(
            falhas,
            [],
            "sem o FOR UPDATE as vinte tinham de colidir; se nenhuma falhou, "
            "o que o criterio 3 mede nao e a tranca",
        )
        self.assertEqual(
            set(falhas),
            {"23505"},
            f"a colisao tem de ser a unicidade do ledger, e deu {set(falhas)}",
        )


def _appendar_sem_tranca(tenant: str, cobranca: str, conta: str):
    """Igual ao `_appendar_noutra_ligacao`, mas pela copia sem `FOR UPDATE`."""
    conexao = ligacao.ligar("app")
    try:
        cursor = conexao.cursor()
        cursor.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant,))
        cursor.fetchone()
        cursor.execute(
            "SELECT * FROM platform.append_sem_tranca("
            "p_charge_id => %s, p_tipo_evento => 'pagamento_orfao', "
            "p_account_id => %s, p_valor_minor => %s, p_authn_method => 'hmac', "
            "p_authn_ok => true, p_decisao => 'informativo', "
            "p_payload => '{}'::jsonb)",
            (cobranca, conta, VALOR),
        )
        sequencia = cursor.fetchone()[1]
        conexao.commit()
        return sequencia, None
    except pg8000.dbapi.DatabaseError as erro:
        conexao.rollback()
        return None, sqlstate(erro)
    finally:
        conexao.close()
