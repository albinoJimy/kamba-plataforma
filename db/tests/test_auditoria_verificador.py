"""O verificador da cadeia e a ancora diaria (KAM-012, criterios 5 e 6).

O criterio 5 pede que adulterar uma linha seja **detectado na execucao
seguinte** do *job* de verificacao. Esta bateria adultera de verdade e exige a
deteccao, e por cada uma das tres formas de o fazer — apagar uma linha do
meio, alterar uma coluna, apagar linhas do fim.

**Como se adultera, e porque nao e com `session_replication_role`.** O bloco
do ticket propoe `SET session_replication_role = replica`. Medido na revisao
0006: isso contorna um *trigger* normal e **nao** contorna um `ENABLE ALWAYS`,
e escolheu-se o `ALWAYS` por ser a proteccao mais forte. O caminho que resta é
`ALTER TABLE ... DISABLE TRIGGER`, que exige ser dono da tabela e que nao se
faz por engano — e e precisamente o que se quer de um ambiente de teste: a
adulteracao tem de ser possivel aqui e dificil em producao.
"""

from __future__ import annotations

import datetime
import tempfile
import unittest
from pathlib import Path

import auditoria
from tests import factories
from tests.base import ComBase

GENESE = bytes(32)


class ComCadeia(ComBase):
    """Um tenant com algumas linhas de auditoria, e as ferramentas de as partir."""

    def setUp(self) -> None:
        super().setUp()
        self.ligacao = self.ligar("admin")
        self.cursor = self.ligacao.cursor()
        self.tenant = factories.tenant(self.cursor)
        for n in range(4):
            self.cursor.execute(
                "SELECT platform.audit_append(%s,'staff','op','price.update','produto',%s,"
                "NULL, sha256(%s))",
                (self.tenant, f"sku-{n}", f"v{n}"),
            )

    def sem_trigger(self, sql: str, parametros: tuple = ()) -> None:
        """Corre uma instrucao com o *trigger* de imutabilidade desligado."""
        self.cursor.execute(
            "ALTER TABLE platform.audit_log DISABLE TRIGGER audit_log_sem_update_nem_delete"
        )
        try:
            self.cursor.execute(sql, parametros)
        finally:
            self.cursor.execute(
                "ALTER TABLE platform.audit_log "
                "ENABLE ALWAYS TRIGGER audit_log_sem_update_nem_delete"
            )

    def ids(self) -> list[int]:
        self.cursor.execute(
            "SELECT id FROM platform.audit_log WHERE tenant_id = %s ORDER BY id",
            (self.tenant,),
        )
        return [int(linha[0]) for linha in self.cursor.fetchall()]

    def achados(self) -> list[str]:
        return auditoria.verificar(self.cursor, self.tenant)


class TestCadeiaIntacta(ComCadeia):
    def test_sem_adulteracao_nao_ha_achados(self) -> None:
        """A base de todas as outras: se isto falhasse, tudo o resto era vacuo."""
        self.assertEqual(self.achados(), [])

    def test_o_verificador_nao_usa_a_funcao_que_escreveu(self) -> None:
        """A formula esta duas vezes, e e a divergencia que tem valor.

        Se o verificador chamasse `platform.audit_row_hash`, um defeito **nela**
        aparecia dos dois lados e a verificacao dava sempre certo. Prova-se
        aqui que o Python chega ao mesmo valor que o SQL guardou.
        """
        self.cursor.execute(
            "SELECT tenant_id, actor_type, actor_id, action, entity, entity_id, "
            "       turn_id, payload_hash, prev_hash, row_hash "
            "  FROM platform.audit_log WHERE tenant_id = %s ORDER BY id LIMIT 1",
            (self.tenant,),
        )
        linha = self.cursor.fetchone()
        self.assertEqual(
            auditoria.row_hash(bytes(linha[8]), linha[0], linha[1], linha[2], linha[3],
                               linha[4], linha[5], linha[6], bytes(linha[7])),
            bytes(linha[9]),
        )


class TestAdulteracaoDetectada(ComCadeia):
    """As tres formas de partir a cadeia, e a mensagem de cada uma."""

    def test_alterar_uma_coluna_da_hash_errado(self) -> None:
        alvo = self.ids()[1]
        self.sem_trigger(
            "UPDATE platform.audit_log SET actor_id = 'outro' WHERE id = %s", (alvo,)
        )
        achados = self.achados()
        self.assertTrue(any("hash errado" in a for a in achados), achados)
        self.assertTrue(any(str(alvo) in a for a in achados), achados)

    def test_apagar_uma_linha_do_meio_parte_o_elo(self) -> None:
        alvo = self.ids()[1]
        self.sem_trigger("DELETE FROM platform.audit_log WHERE id = %s", (alvo,))
        achados = self.achados()
        self.assertTrue(any("elo partido" in a for a in achados), achados)

    def test_apagar_do_fim_so_a_cabeca_apanha(self) -> None:
        """O caso que justifica o `audit_heads` existir para alem do desempenho.

        Apagadas as ultimas linhas, a cadeia fica **consistente consigo
        propria**: cada elo aponta para o anterior. O que denuncia o
        apagamento e a cabeca, que continua a apontar para um elo que ja nao
        existe.
        """
        ultimos = self.ids()[-2:]
        self.sem_trigger(
            "DELETE FROM platform.audit_log WHERE id = ANY(%s)", (ultimos,)
        )
        achados = self.achados()
        self.assertTrue(any("cabeca errada" in a for a in achados), achados)
        self.assertFalse(any("elo partido" in a for a in achados), achados)

    def test_inserir_uma_linha_forjada_parte_o_elo(self) -> None:
        """Escrever directamente, sem passar pelo `audit_append`."""
        self.cursor.execute(
            "INSERT INTO platform.audit_log "
            "(tenant_id, actor_type, actor_id, action, entity, entity_id, "
            " payload_hash, prev_hash, row_hash) "
            "VALUES (%s,'staff','forjado','price.update','p','x', sha256('f'), "
            "        sha256('g'), sha256('h'))",
            (self.tenant,),
        )
        achados = self.achados()
        self.assertTrue(any("elo partido" in a for a in achados), achados)
        self.assertTrue(any("hash errado" in a for a in achados), achados)


class TestAncora(ComCadeia):
    def test_a_ancora_tem_o_ultimo_elo_de_cada_cadeia(self) -> None:
        import json

        with tempfile.TemporaryDirectory() as pasta:
            caminho = auditoria.ancorar(self.cursor, destino=Path(pasta))
            conteudo = json.loads(caminho.read_text(encoding="utf-8"))
        self.cursor.execute(
            "SELECT encode(row_hash, 'hex') FROM platform.audit_log "
            " WHERE tenant_id = %s ORDER BY id DESC LIMIT 1",
            (self.tenant,),
        )
        esperado = self.cursor.fetchone()[0]
        self.assertEqual(conteudo["cadeias"][self.tenant]["row_hash"], esperado)

    def test_a_ancora_e_reproduzivel_a_partir_da_base(self) -> None:
        """Duas execucoes sobre as mesmas linhas dao o mesmo ficheiro, byte a byte.

        E o que torna a ancora util: duas copias que divirjam dizem que uma
        das bases mudou.
        """
        with tempfile.TemporaryDirectory() as pasta:
            primeira = auditoria.ancorar(self.cursor, destino=Path(pasta)).read_bytes()
            segunda = auditoria.ancorar(self.cursor, destino=Path(pasta)).read_bytes()
        self.assertEqual(primeira, segunda)

    def test_o_dia_fecha_a_ancora(self) -> None:
        """Uma ancora de ontem nao leva as linhas de hoje."""
        import json

        ontem = datetime.datetime.now(datetime.timezone.utc).date() - datetime.timedelta(days=1)
        with tempfile.TemporaryDirectory() as pasta:
            caminho = auditoria.ancorar(self.cursor, dia=ontem, destino=Path(pasta))
            conteudo = json.loads(caminho.read_text(encoding="utf-8"))
        self.assertNotIn(self.tenant, conteudo["cadeias"])
        self.assertEqual(conteudo["dia"], ontem.isoformat())


if __name__ == "__main__":
    unittest.main()
