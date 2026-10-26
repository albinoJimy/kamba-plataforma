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
            "SELECT tgenabled::text FROM pg_trigger "
            " WHERE tgrelid = 'platform.audit_log'::regclass "
            "   AND tgname = 'audit_log_sem_update_nem_delete'"
        )
        marca = self.cursor.fetchone()[0]
        self.cursor.execute(
            "ALTER TABLE platform.audit_log DISABLE TRIGGER audit_log_sem_update_nem_delete"
        )
        # E o de encadear: sem o desligar, o `INSERT` do caso de adulteracao
        # era reescrito pelo proprio trigger — que e a propriedade, e por isso
        # mesmo nao serve para **simular** uma adulteracao.
        self.cursor.execute(
            "ALTER TABLE platform.audit_log DISABLE TRIGGER audit_log_encadear"
        )
        try:
            self.cursor.execute(sql, parametros)
        finally:
            # Repoe **o que leu**, e nao o que se desejava: religar sempre com
            # `ENABLE ALWAYS` e DDL confirmado que repara a base viva e esconde
            # regressoes de esquema de tudo o que corre depois.
            palavra = {"A": "ENABLE ALWAYS", "R": "ENABLE REPLICA", "D": "DISABLE"}.get(
                marca, "ENABLE"
            )
            self.cursor.execute(
                f"ALTER TABLE platform.audit_log {palavra} "
                "TRIGGER audit_log_sem_update_nem_delete"
            )
            self.cursor.execute(
                "ALTER TABLE platform.audit_log ENABLE ALWAYS TRIGGER audit_log_encadear"
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
            "SELECT tenant_id, criado_at, actor_type, actor_id, action, entity, "
            "       entity_id, turn_id, payload_hash, prev_hash, row_hash "
            "  FROM platform.audit_log WHERE tenant_id = %s ORDER BY id LIMIT 1",
            (self.tenant,),
        )
        linha = self.cursor.fetchone()
        self.assertEqual(
            auditoria.row_hash(bytes(linha[9]), linha[1], linha[0], linha[2], linha[3],
                               linha[4], linha[5], linha[6], linha[7], bytes(linha[8])),
            bytes(linha[10]),
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

    def test_apagar_uma_linha_do_meio_deixa_as_seguintes_fora_da_cadeia(self) -> None:
        """A cadeia percorre-se pelo `prev_hash`, nao pelo `id`.

        Medido: o `id` sai da sequencia quando a instrucao comeca e o lugar na
        cadeia decide-se depois, no trigger — com mil insercoes concorrentes
        as duas ordens divergem. Apagada uma linha do meio, as seguintes ficam
        sem ponte ate a genese, e e isso que se deteta.
        """
        alvo = self.ids()[1]
        self.sem_trigger("DELETE FROM platform.audit_log WHERE id = %s", (alvo,))
        achados = self.achados()
        self.assertTrue(any("nao esta na cadeia" in a for a in achados), achados)

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
        self.assertFalse(any("nao esta na cadeia" in a for a in achados), achados)

    def test_uma_linha_forjada_e_reescrita_pelo_trigger(self) -> None:
        """Inserir com hashes a escolha **nao** forja nada: o trigger reescreve.

        Na primeira versao desta revisao isto partia a cadeia, porque os
        valores do chamador ficavam. Hoje o trigger ignora-os, e o que se
        verifica e que a cadeia continua intacta — que e a propriedade.
        """
        self.cursor.execute(
            "INSERT INTO platform.audit_log "
            "(tenant_id, actor_type, actor_id, action, entity, entity_id, "
            " payload_hash, prev_hash, row_hash) "
            "VALUES (%s,'staff','forjado','price.update','p','x', sha256('f'), "
            "        sha256('g'), sha256('h'))",
            (self.tenant,),
        )
        self.assertEqual(self.achados(), [])
        self.cursor.execute(
            "SELECT prev_hash = sha256('g'), row_hash = sha256('h') "
            "  FROM platform.audit_log WHERE actor_id = 'forjado'"
        )
        self.assertEqual(tuple(self.cursor.fetchone()), (False, False))

    def test_apagar_e_reinserir_com_outra_data_e_detectado(self) -> None:
        """O `criado_at` entrou no hash (achado M5 da revisao adversarial).

        Sem ele, apagar a ultima linha e reinseri-la com o mesmo conteudo dava
        outra data e a cadeia ficava «intacta» — a sequencia era a prova de
        adulteracao e a cronologia nao era de todo.
        """
        alvo = self.ids()[-1]
        self.cursor.execute(
            "SELECT prev_hash, row_hash FROM platform.audit_log WHERE id = %s", (alvo,)
        )
        prev, antigo = (bytes(v) for v in self.cursor.fetchone())
        self.sem_trigger("DELETE FROM platform.audit_log WHERE id = %s", (alvo,))
        # Reinsere a mesma linha, com o mesmo encadeamento e outra data. Sem o
        # `criado_at` no hash, o `row_hash` dava igual e nada se notava.
        self.sem_trigger(
            "INSERT INTO platform.audit_log "
            "(criado_at, tenant_id, actor_type, actor_id, action, entity, entity_id, "
            " payload_hash, prev_hash, row_hash) "
            "VALUES (timestamptz '2019-05-05 00:00:00+00', %s,'staff','op',"
            "'price.update','produto','sku-3', sha256('v3'), %s, %s)",
            (self.tenant, prev, antigo),
        )
        achados = self.achados()
        self.assertTrue(any("hash errado" in a for a in achados), achados)

    def test_uma_cadeia_que_desaparece_inteira_so_a_ancora_apanha(self) -> None:
        """O achado M4: o verificador percorre o que existe.

        Apagadas as linhas de um tenant **e** a sua cabeca, nao ha nada para
        percorrer e nao ha achado. A defesa e a ancora do dia anterior, que
        sabe que a cadeia existia.
        """
        import json
        import tempfile

        with tempfile.TemporaryDirectory() as pasta:
            caminho = auditoria.ancorar(self.cursor, destino=Path(pasta))
            ancora = json.loads(caminho.read_text(encoding="utf-8"))
        self.sem_trigger(
            "DELETE FROM platform.audit_log WHERE tenant_id = %s", (self.tenant,)
        )
        self.cursor.execute(
            "DELETE FROM platform.audit_heads WHERE tenant_id = %s", (self.tenant,)
        )
        self.assertEqual(auditoria.verificar(self.cursor, self.tenant), [])
        achados = auditoria.verificar(self.cursor, self.tenant, ancora)
        self.assertTrue(any("desapareceu inteira" in a for a in achados), achados)


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

    def test_a_ancora_nao_depende_do_fuso_da_sessao(self) -> None:
        """O achado M2: a fronteira do dia usava o `TimeZone` da sessao.

        `criado_at < (date + 1)` promove o `date` com o fuso da sessao, e com
        `Africa/Luanda` — que e a omissao de `tenants.fuso_horario` — a mesma
        base no mesmo dia dava outra ancora. A afirmacao «reproduzivel a partir
        da base» era falsa fora de uma sessao de fuso fixo.

        **Este teste matava a mutacao numa hora em vinte e quatro, e sobreviveu
        a noite de 2026-10-26 por isso.** As linhas do `setUp` tem
        `criado_at = now()` e a ancora era do dia de hoje, pelo que ficavam
        abaixo das **duas** fronteiras — a fixa em UTC e a que o fuso desloca
        uma hora — e as duas ancoras saiam iguais com a fronteira errada. So
        entre as 23:00 e as 00:00 UTC e que as duas leituras discordavam sobre
        uma linha de `now()`.

        Por isso a linha passa a estar **dentro** da hora em que discordam:
        recua-se o ultimo elo para as 23:30 UTC de ontem e ancora-se ontem. A
        fronteira certa — `(ontem + 1) AT TIME ZONE 'UTC'`, isto e, hoje as
        00:00 UTC — inclui-a sempre; a fronteira do fuso de Luanda cai em ontem
        as 23:00 UTC e deixa-a de fora. Deterministico a qualquer hora do dia.
        """
        import json

        ontem = datetime.datetime.now(datetime.timezone.utc).date() - datetime.timedelta(
            days=1
        )
        na_hora_da_divergencia = datetime.datetime.combine(
            ontem, datetime.time(23, 30), tzinfo=datetime.timezone.utc
        )
        self.sem_trigger(
            "UPDATE platform.audit_log SET criado_at = %s WHERE id = ("
            "  SELECT max(id) FROM platform.audit_log WHERE tenant_id = %s)",
            (na_hora_da_divergencia, self.tenant),
        )
        with tempfile.TemporaryDirectory() as pasta:
            self.cursor.execute("SET TimeZone = 'UTC'")
            em_utc = auditoria.ancorar(
                self.cursor, dia=ontem, destino=Path(pasta)
            ).read_bytes()
            self.cursor.execute("SET TimeZone = 'Africa/Luanda'")
            em_luanda = auditoria.ancorar(
                self.cursor, dia=ontem, destino=Path(pasta)
            ).read_bytes()
            self.cursor.execute("SET TimeZone = 'UTC'")

        # O canario: sem isto, uma ancora **vazia** nos dois fusos passava o
        # teste — e vazia e exactamente o que sai se a linha recuada nao entrar
        # em nenhuma das duas leituras. O que se quer e que ela entre nas duas.
        self.assertIn(
            self.tenant,
            json.loads(em_utc.decode("utf-8"))["cadeias"],
            "a linha recuada nao entrou na ancora de ontem",
        )
        self.assertEqual(em_utc, em_luanda)

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
