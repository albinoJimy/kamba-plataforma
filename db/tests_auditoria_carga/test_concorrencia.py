"""Criterio 3 do KAM-012: mil insercoes concorrentes dao uma cadeia linear.

Suite propria, pela mesma razao que a carga de eventos do KAM-005: mil
insercoes com mil ligacoes custam minutos, e uma suite custa isso **por cada
mutacao** que a escolha (`db/mutacoes.py`). Dentro de `tests`, cada mutacao do
`audit_append` passava a custar esse tempo, e a prova por mutacao nocturna
(KAM-143) nao se paga assim.

Nao e uma suite «opcional»: `make ci-8` corre-a, e uma bifurcacao falha o
build como qualquer outra.

## O que «linear» quer dizer, em tres invariantes

    sem bifurcacao   nao ha dois `prev_hash` iguais. Duas linhas que partam do
                     mesmo elo sao duas versoes da historia.
    sem buraco       o conjunto dos `prev_hash` e o conjunto dos `row_hash`
                     menos o ultimo, mais a genese.
    cabeca certa     o `last_hash` e o `row_hash` do ultimo elo.

O primeiro e o que a concorrencia ataca, e e o que a restricao
`UNIQUE (row_hash)` da revisao 0006 torna **impossivel de escrever** em vez de
detectavel depois. Esta suite verifica que a serializacao funciona sem ela ter
de disparar: se disparasse, havia excepcoes, e o teste conta-as.
"""

from __future__ import annotations

import concurrent.futures
import unittest

import auditoria
import ligacao
from tests import factories
from tests.base import ComBase

#: O numero do criterio. Nao e folga.
INSERCOES = 1000

#: Quantas ligacoes em paralelo. Uma por insercao era um milhar de ligacoes
#: abertas ao mesmo tempo, que estoura o `max_connections` por omissao (100) e
#: media a gestao do *pool* e nao a serializacao da cadeia. Com 32, ha sempre
#: dezenas de transaccoes a disputar a mesma cabeca, que e o que se quer.
LIGACOES = 32


class TestMilInsercoesConcorrentes(ComBase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        ligacao_de_preparacao = ligacao.ligar("admin")
        cursor = ligacao_de_preparacao.cursor()
        cls.tenant = factories.tenant(cursor)
        ligacao_de_preparacao.commit()
        cls._preparacao = ligacao_de_preparacao

        cls.excepcoes: list[str] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=LIGACOES) as piscina:
            tarefas = [piscina.submit(cls._escrever, n) for n in range(INSERCOES)]
            for tarefa in concurrent.futures.as_completed(tarefas):
                erro = tarefa.result()
                if erro:
                    cls.excepcoes.append(erro)

    @classmethod
    def _escrever(cls, n: int) -> str | None:
        """Uma insercao, numa ligacao propria, com `commit`."""
        conexao = ligacao.ligar("batch")
        try:
            cursor = conexao.cursor()
            cursor.execute(
                "SELECT platform.audit_append(%s,'agent','carga','stock.adjust','sku',%s,"
                "NULL, sha256(%s))",
                (cls.tenant, f"sku-{n}", str(n)),
            )
            cursor.fetchall()
            conexao.commit()
            return None
        except Exception as erro:  # noqa: BLE001 — queremos a mensagem, seja qual for
            return f"{type(erro).__name__}: {erro}"
        finally:
            conexao.close()

    @classmethod
    def tearDownClass(cls) -> None:
        cursor = cls._preparacao.cursor()
        cursor.execute(
            "ALTER TABLE platform.audit_log DISABLE TRIGGER audit_log_sem_update_nem_delete"
        )
        cursor.execute("DELETE FROM platform.audit_log WHERE tenant_id = %s", (cls.tenant,))
        cursor.execute(
            "ALTER TABLE platform.audit_log "
            "ENABLE ALWAYS TRIGGER audit_log_sem_update_nem_delete"
        )
        cursor.execute("DELETE FROM platform.audit_heads WHERE tenant_id = %s", (cls.tenant,))
        cursor.execute("DELETE FROM platform.tenants WHERE id = %s", (cls.tenant,))
        cls._preparacao.commit()
        cls._preparacao.close()
        super().tearDownClass()

    def setUp(self) -> None:
        super().setUp()
        self.cursor = self.ligar("admin").cursor()

    def test_nenhuma_insercao_falhou(self) -> None:
        """A serializacao tem de aguentar, e nao de recusar metade.

        Uma `unique_violation` aqui seria a restricao `UNIQUE (row_hash)` a
        salvar a cadeia — o que esta certo, mas quer dizer que o bloqueio da
        cabeca nao serializou. A cadeia ficaria intacta e mil insercoes dariam
        menos de mil linhas.
        """
        self.assertEqual(self.excepcoes[:5], [], f"{len(self.excepcoes)} falha(s)")

    def test_sao_mil_linhas(self) -> None:
        self.cursor.execute(
            "SELECT count(*) FROM platform.audit_log WHERE tenant_id = %s", (self.tenant,)
        )
        self.assertEqual(int(self.cursor.fetchone()[0]), INSERCOES)

    def test_nao_ha_bifurcacao(self) -> None:
        """Dois `prev_hash` iguais sao duas versoes da historia."""
        self.cursor.execute(
            "SELECT count(*), count(DISTINCT prev_hash) FROM platform.audit_log "
            " WHERE tenant_id = %s",
            (self.tenant,),
        )
        total, distintos = self.cursor.fetchone()
        self.assertEqual(int(total), int(distintos))

    def test_a_cadeia_e_linear_de_ponta_a_ponta(self) -> None:
        """O verificador, sobre mil elos escritos em paralelo."""
        self.assertEqual(auditoria.verificar(self.cursor, self.tenant), [])

    def test_a_cabeca_aponta_para_o_fim_da_cadeia(self) -> None:
        """O fim da cadeia e a linha que **ninguem aponta**, e nao o maior `id`.

        Medido: o `id` sai da sequencia quando a instrucao comeca e o lugar na
        cadeia decide-se depois, quando o trigger bloqueia a cabeca. Com mil
        insercoes concorrentes as duas ordens divergem — este teste comparava
        a cabeca com `ORDER BY id DESC LIMIT 1` e falhava sem nada estar
        errado. A cadeia diz a sua propria ordem.
        """
        self.cursor.execute(
            "SELECT h.last_hash = (SELECT a.row_hash FROM platform.audit_log a "
            "                       WHERE a.tenant_id = %s "
            "                         AND NOT EXISTS (SELECT 1 FROM platform.audit_log b "
            "                                          WHERE b.tenant_id = a.tenant_id "
            "                                            AND b.prev_hash = a.row_hash)) "
            "  FROM platform.audit_heads h WHERE h.tenant_id = %s",
            (self.tenant, self.tenant),
        )
        self.assertTrue(self.cursor.fetchone()[0])


if __name__ == "__main__":
    unittest.main()
