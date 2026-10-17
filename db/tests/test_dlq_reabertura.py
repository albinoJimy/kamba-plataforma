"""Um evento que volta a falhar depois de resolvido (KAM-006).

O caso que isto fecha, e que nenhum teste tinha:

    um evento falha seis vezes e entra na DLQ;
    alguem reprocessa-o — a entrada passa a `reprocessada`;
    o reprocessamento volta a falhar seis vezes.

Com uma unicidade sobre `(consumer, event_id)` inteira, a segunda falha colidia
com a linha **fechada** e o `ON CONFLICT DO NOTHING` nao escrevia nada: ficava
uma DLQ com zero entradas abertas sobre um efeito que continua por aplicar,
`evt_dlq_open` a zero, alerta nenhum, e a retencao de 30 dias a apagar a unica
evidencia. Num `payment.*`, um Sev1 que se apaga a si proprio.

A resposta e a unicidade **parcial** (`events_dlq_aberta_uq`, so sobre as
abertas). As duas propriedades separam-se: duas falhas na mesma execucao
continuam a dar uma entrada, e um ciclo novo depois de uma resolucao abre a
sua, com a anterior guardada.

## Porque e que isto corre com `SET LOCAL ROLE`

Corre com o **SQL do modulo** e com os **papeis do modulo**, porque o que ha a
provar e tanto o SQL como os privilegios: `kamba_app` escreve sem `SELECT` nem
`UPDATE` nenhum nesta tabela — e e isso que faz a regra dos dois aprovadores
valer tambem contra codigo. Um teste que corresse tudo como administrador nao
notaria a falta deles.

Mas nada se confirma (a `ComBase` desfaz tudo), pelo que o leitor tem de ser a
**mesma transaccao** de quem escreveu. Dai o `SET LOCAL ROLE`: uma ligacao de
administrador, que muda de papel para escrever e volta para ler. Sob
`SET ROLE kamba_app` a RLS aplica-se e os privilegios tambem — o papel efectivo
deixa de ser o superutilizador.
"""

from __future__ import annotations

import json
import unittest
import uuid

from tests.base import PRIVILEGIO_INSUFICIENTE, ComBase, ConsultaDoTypeScript

CONSUMER = "ensaio-reabertura"


def _envelope(event_id: str, tenant_id: str) -> str:
    return json.dumps(
        {
            "id": event_id,
            "tipo": "payment.confirmed",
            "versao": 1,
            "tenant_id": tenant_id,
            "agregado": {"tipo": "order", "id": "ORD-1", "seq": 1},
            "classe_pii": "P1",
            "finalidades": ["transacao"],
            "payload": {"order_id": "ORD-1"},
        }
    )


class ComEntradaNaDlq(ComBase):
    """Uma ligacao de administrador que muda de papel para cada acto."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.para_dlq = ConsultaDoTypeScript("SQL_PARA_DLQ")
        cls.definir_tenant = ConsultaDoTypeScript("SQL_DEFINIR_TENANT")

    def setUp(self) -> None:
        super().setUp()
        self.tenant = str(uuid.uuid4())
        self.event_id = str(uuid.uuid4())
        self.cursor = self.ligar("admin").cursor()
        # O contexto da RLS, que vale para a transaccao inteira e sobrevive a
        # cada `SET LOCAL ROLE`.
        self.cursor.execute(
            self.definir_tenant.sql, self.definir_tenant.args(self.tenant, True)
        )
        self.cursor.fetchone()

    def como(self, papel: str, sql: str, parametros: tuple = ()) -> int:
        """Corre `sql` com o papel pedido, na mesma transaccao. Devolve as linhas."""
        self.cursor.execute(f"SET LOCAL ROLE {papel}")
        try:
            self.cursor.execute(sql, parametros)
            return int(self.cursor.rowcount)
        finally:
            self.cursor.execute("RESET ROLE")

    def escrever(self, erro: str, tentativas: int = 6) -> int:
        """O `SQL_PARA_DLQ` como o `paraDlq()` o chama, com o papel que o chama."""
        return self.como(
            "kamba_app",
            self.para_dlq.sql,
            self.para_dlq.args(
                CONSUMER,
                self.event_id,
                "payment.confirmed",
                1,
                self.tenant,
                _envelope(self.event_id, self.tenant),
                erro,
                tentativas,
            ),
        )

    def fechar_como_reprocessada(self) -> int:
        """O que a CLI faz, com o papel que a CLI usa."""
        return self.como(
            "kamba_batch",
            "UPDATE platform.events_dlq "
            "   SET estado = 'reprocessada', resolvido_at = now(), "
            "       resolvido_por = 'alguem' "
            " WHERE consumer = %s AND event_id = %s AND estado = 'aberta'",
            (CONSUMER, self.event_id),
        )

    def entradas(self) -> list[tuple]:
        """`(estado, erro, resolvido_por)` de cada entrada, da mais antiga."""
        self.cursor.execute(
            "SELECT estado, erro, resolvido_por FROM platform.events_dlq "
            " WHERE consumer = %s AND event_id = %s ORDER BY id",
            (CONSUMER, self.event_id),
        )
        return [tuple(linha) for linha in self.cursor.fetchall()]


class TestReentrada(ComEntradaNaDlq):
    def test_a_primeira_falha_abre_uma_entrada(self) -> None:
        self.assertEqual(self.escrever("falhou"), 1)
        self.assertEqual(self.entradas(), [("aberta", "falhou", None)])

    def test_sobre_uma_entrada_aberta_nao_escreve_nada(self) -> None:
        """Duas falhas na mesma execucao nao dao duas entradas nem dois alertas."""
        self.assertEqual(self.escrever("falhou"), 1)
        self.assertEqual(self.escrever("falhou outra vez"), 0)
        self.assertEqual(self.entradas(), [("aberta", "falhou", None)])

    def test_um_ciclo_novo_depois_de_uma_resolucao_abre_a_sua_entrada(self) -> None:
        """**O caso que importa.** Sem isto, a segunda falha desaparecia."""
        self.escrever("falhou")
        self.assertEqual(self.fechar_como_reprocessada(), 1)
        self.assertEqual(self.entradas(), [("reprocessada", "falhou", "alguem")])

        self.assertEqual(
            self.escrever("falhou depois do reprocessamento"),
            1,
            "a segunda falha nao deixou entrada: o efeito fica por aplicar e sem registo",
        )
        self.assertEqual(
            self.entradas(),
            [
                ("reprocessada", "falhou", "alguem"),
                ("aberta", "falhou depois do reprocessamento", None),
            ],
            "a entrada anterior tem de ficar: e o historico que a auditoria le",
        )

    def test_so_ha_uma_aberta_de_cada_vez(self) -> None:
        """A propriedade que a unicidade parcial impoe, dita por extenso."""
        self.escrever("primeira")
        self.fechar_como_reprocessada()
        self.escrever("segunda")
        self.escrever("segunda outra vez")
        abertas = [e for e in self.entradas() if e[0] == "aberta"]
        self.assertEqual(len(abertas), 1)


class TestQuemEscreveNaoLeNemFecha(ComEntradaNaDlq):
    """Os privilegios que fazem a regra dos dois aprovadores valer contra codigo."""

    def test_le_o_estado_e_so_o_estado(self) -> None:
        """A coluna que o predicado do `ON CONFLICT` obriga a avaliar.

        Sem este `SELECT` por coluna, o proprio `INSERT` falha com `permission
        denied for table events_dlq`: a cláusula de inferencia e uma expressao
        sobre a tabela, e as suas colunas contam como leitura. Medido no gate 8.
        """
        self.escrever("falhou")
        self.cursor.execute("SET LOCAL ROLE kamba_app")
        try:
            self.cursor.execute(
                "SELECT estado FROM platform.events_dlq WHERE consumer = %s",
                (CONSUMER,),
            )
            self.assertEqual([tuple(l) for l in self.cursor.fetchall()], [("aberta",)])
        finally:
            self.cursor.execute("RESET ROLE")

    def test_nao_le_a_tabela(self) -> None:
        """O `id` e sequencial: le-lo media o volume de falhas do vizinho."""
        self.escrever("falhou")
        self.cursor.execute("SET LOCAL ROLE kamba_app")
        try:
            self.assertErroSql(
                PRIVILEGIO_INSUFICIENTE,
                self.cursor,
                "SELECT id FROM platform.events_dlq",
            )
        finally:
            self.cursor.execute("RESET ROLE")

    def test_nao_fecha_uma_entrada(self) -> None:
        """Sem `UPDATE`, quem consome nao resolve nada sozinho.

        E a outra metade da regra dos dois aprovadores: a CLI exige duas
        pessoas, e isto exige que **nenhum** processo a possa contornar.
        """
        self.escrever("falhou")
        self.cursor.execute("SET LOCAL ROLE kamba_app")
        try:
            self.assertErroSql(
                PRIVILEGIO_INSUFICIENTE,
                self.cursor,
                "UPDATE platform.events_dlq SET estado = 'descartada' "
                " WHERE consumer = %s",
                (CONSUMER,),
            )
        finally:
            self.cursor.execute("RESET ROLE")

    def test_nao_apaga_uma_entrada(self) -> None:
        self.escrever("falhou")
        self.cursor.execute("SET LOCAL ROLE kamba_app")
        try:
            self.assertErroSql(
                PRIVILEGIO_INSUFICIENTE,
                self.cursor,
                "DELETE FROM platform.events_dlq WHERE consumer = %s",
                (CONSUMER,),
            )
        finally:
            self.cursor.execute("RESET ROLE")


if __name__ == "__main__":
    unittest.main()
