"""O `downgrade` da `0030`: **recusa-se a ser destrutivo**, e deixa o que nao criou.

«Migracao reversivel» e uma caixa da Definition of Done, e os *Detalhes
Tecnicos* do bloco pedem mais do que isso: «sem `downgrade` destrutivo em
`orders_mirror`, `order_state_log` (so aditivo)», que e o §11 de
`docs/tecnica/03` por escrito.

O ciclo `upgrade -> downgrade -> upgrade` ja corre no *gate* 8
(`tests/test_migracao.TestCiclo`), e sobre uma base **vazia**. O que esse ciclo
nao ve e o que esta classe mede:

```text
com linhas e sem a variavel   o `downgrade` **recusa** e nao apaga nada
com linhas e com a variavel   escreve a copia logica e desce
a copia                       tem as linhas das quatro tabelas, uma por linha
o `deny_mutation`             **fica**: e da `0029`, e nao e desta revisao
```

A primeira e a que importa: um `downgrade` que apagasse o `order_state_log` de
uma base com encomendas apagava a prova de que cada `paga` veio de um evento
autenticado — e essa prova nao se reconstroi de sitio nenhum.

Esta classe **nao** herda de `ComEncomendas`: controla ela propria a revisao em
que a base esta, como o `TestDowngradeDa0029` do KAM-053. Repoe `head` no fim,
corra bem ou mal.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
import uuid
from pathlib import Path

import bootstrap
import ligacao
from tests.base import alembic, alembic_ok, em_head, exigir_base_descartavel

#: As cinco tabelas que a revisao cria, e que o `downgrade` tem de levar.
TABELAS = (
    "order_intents",
    "order_reconciliation_issues",
    "order_state_graph",
    "order_state_log",
    "orders_mirror",
)

#: As quatro funcoes que ela cria. O `deny_mutation` **nao** esta aqui: e da
#: `0029`, e o `downgrade` desta nao o apaga.
FUNCOES = (
    "order_estado_exige_log",
    "order_nasce_criada",
    "order_numero_publico",
    "order_transicao_valida",
)

#: A revisao anterior. O `downgrade` desta volta aqui.
ANTERIOR = "0029"

#: A variavel que autoriza a perda.
VARIAVEL = "KAMBA_DOWNGRADE_0030_COPIA"


class TestDowngradeDa0030(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        exigir_base_descartavel()
        bootstrap.aplicar()
        if not em_head():
            alembic_ok("upgrade", "head")

    def setUp(self) -> None:
        self.conexao = ligacao.ligar("admin")
        self.conexao.autocommit = True
        self.cursor = self.conexao.cursor()
        os.environ.pop(VARIAVEL, None)

    def tearDown(self) -> None:
        try:
            os.environ.pop(VARIAVEL, None)
            self._apagar_tudo()
            if not em_head():
                alembic_ok("upgrade", "head")
        finally:
            self.conexao.close()

    # -------------------------------------------------------------- auxiliares

    def _apagar_tudo(self) -> None:
        """Limpa o que o ensaio semeou, se as tabelas existirem.

        O `order_state_log` nao se apaga (o `deny_mutation` recusa), pelo que o
        que se apaga e a encomenda — e para isso a linha do registo tem de sair
        primeiro, o que nao pode. Por isso o ensaio desce a revisao no fim: o
        `DROP TABLE` leva as duas, e a base do *gate* e descartavel.
        """
        self.cursor.execute(
            "SELECT count(*) FROM pg_tables WHERE schemaname = 'platform' "
            "  AND tablename = 'orders_mirror'"
        )
        if int(self.cursor.fetchone()[0]) == 0:
            return
        os.environ[VARIAVEL] = str(
            Path(tempfile.gettempdir()) / f"kamba-0030-{uuid.uuid4().hex}.jsonl"
        )
        alembic_ok("downgrade", ANTERIOR)
        os.environ.pop(VARIAVEL, None)

    def tabelas_existentes(self) -> list[str]:
        self.cursor.execute(
            "SELECT tablename::text FROM pg_tables "
            " WHERE schemaname = 'platform' AND tablename = ANY(%s) ORDER BY 1",
            (list(TABELAS),),
        )
        return [str(linha[0]) for linha in self.cursor.fetchall()]

    def funcoes_existentes(self) -> list[str]:
        self.cursor.execute(
            "SELECT p.proname::text FROM pg_proc p "
            "  JOIN pg_namespace n ON n.oid = p.pronamespace "
            " WHERE n.nspname = 'platform' AND p.proname = ANY(%s) ORDER BY 1",
            (list(FUNCOES),),
        )
        return [str(linha[0]) for linha in self.cursor.fetchall()]

    def _semear(self) -> str:
        """Um tenant com uma encomenda que transitou. Devolve o `tenant_id`."""
        tenant = str(uuid.uuid4())
        self.cursor.execute(
            "INSERT INTO platform.tenants (id, tipo, nome) "
            "VALUES (%s, 'pme', 'Loja do downgrade')",
            (tenant,),
        )
        self.cursor.execute(
            "INSERT INTO platform.contacts (tenant_id) VALUES (%s) "
            "RETURNING contact_id",
            (tenant,),
        )
        contacto = str(self.cursor.fetchone()[0])
        self.cursor.execute(
            "INSERT INTO platform.orders_mirror "
            "       (tenant_id, contact_id, intent_key, total_minor, lines_snapshot) "
            "VALUES (%s, %s, 'ik-downgrade', 1000, '[]'::jsonb) RETURNING id",
            (tenant, contacto),
        )
        encomenda = str(self.cursor.fetchone()[0])
        # **As duas escritas numa transaccao**, e nao em `autocommit`: o
        # `CONSTRAINT TRIGGER` diferido corre no fim de cada transaccao, e em
        # `autocommit` o `UPDATE` do estado era uma transaccao sozinha — sem o
        # registo, e recusada com `KA005`. Medido na segunda corrida da suite.
        self.conexao.autocommit = False
        try:
            self.cursor.execute(
                "UPDATE platform.orders_mirror SET estado = 'cancelada', "
                "       version = version + 1 WHERE id = %s",
                (encomenda,),
            )
            self.cursor.execute(
                "INSERT INTO platform.order_state_log "
                "       (tenant_id, order_id, de, para, version, causa, actor_kind) "
                "VALUES (%s, %s, 'criada', 'cancelada', 2, 'cliente_cancela', "
                "        'agente')",
                (tenant, encomenda),
            )
            self.conexao.commit()
        finally:
            self.conexao.autocommit = True
        return tenant

    # ----------------------------------------------------------------- ensaios

    def test_com_as_tabelas_vazias_desce_e_sobe_sem_pedir_copia(self) -> None:
        """Sem encomendas nao ha nada a perder: o `downgrade` nao pergunta."""
        self.assertEqual(self.tabelas_existentes(), sorted(TABELAS))
        alembic_ok("downgrade", ANTERIOR)
        self.assertEqual(self.tabelas_existentes(), [])
        self.assertEqual(
            self.funcoes_existentes(),
            [],
            "as quatro funcoes caem com a revisao que as criou",
        )
        self.cursor.execute(
            "SELECT count(*) FROM pg_proc p JOIN pg_namespace n "
            "    ON n.oid = p.pronamespace "
            " WHERE n.nspname = 'platform' AND p.proname = 'deny_mutation'"
        )
        self.assertEqual(
            int(self.cursor.fetchone()[0]),
            1,
            "o `deny_mutation` **fica**: e da `0029`, e uma revisao nao apaga o "
            "que nao criou — deixa-lo cair aqui fazia o `downgrade` da `0029` "
            "nao encontrar a funcao que ela criou",
        )
        alembic_ok("upgrade", "head")
        self.assertEqual(self.tabelas_existentes(), sorted(TABELAS))

    def test_com_linhas_e_sem_a_variavel_recusa_e_nao_apaga_nada(self) -> None:
        """A caixa dos *Detalhes Tecnicos*: «sem `downgrade` destrutivo»."""
        self._semear()
        resultado = alembic("downgrade", ANTERIOR)
        saida = resultado.stdout + resultado.stderr
        self.assertNotEqual(
            resultado.returncode, 0, "o passo apagou as encomendas calado"
        )
        self.assertIn("downgrade da 0030 recusado", saida)
        self.assertIn(VARIAVEL, saida, "a mensagem diz como autorizar a perda")
        self.assertEqual(
            self.tabelas_existentes(),
            sorted(TABELAS),
            "recusou **antes** de apagar: as cinco tabelas continuam la",
        )
        self.cursor.execute("SELECT count(*) FROM platform.order_state_log")
        self.assertEqual(int(self.cursor.fetchone()[0]), 1)

    def test_com_a_variavel_escreve_a_copia_e_desce(self) -> None:
        tenant = self._semear()
        destino = Path(tempfile.gettempdir()) / f"kamba-0030-{uuid.uuid4().hex}.jsonl"
        os.environ[VARIAVEL] = str(destino)
        try:
            alembic_ok("downgrade", ANTERIOR)
            self.assertEqual(self.tabelas_existentes(), [])
            linhas = [
                json.loads(linha)
                for linha in destino.read_text(encoding="utf-8").splitlines()
            ]
            por_tabela: dict[str, int] = {}
            for registo in linhas:
                por_tabela[registo["tabela"]] = por_tabela.get(registo["tabela"], 0) + 1
            self.assertEqual(
                por_tabela,
                {"order_state_log": 1, "orders_mirror": 1},
                "a copia tem as linhas que havia, e so essas",
            )
            encomenda = next(
                r["linha"] for r in linhas if r["tabela"] == "orders_mirror"
            )
            self.assertEqual(encomenda["tenant_id"], tenant)
            self.assertEqual(encomenda["estado"], "cancelada")
            registo = next(
                r["linha"] for r in linhas if r["tabela"] == "order_state_log"
            )
            self.assertEqual(
                (registo["de"], registo["para"], registo["causa"]),
                ("criada", "cancelada", "cliente_cancela"),
                "o rasto da transicao fica na copia: e a unica prova que nao se "
                "reconstroi de sitio nenhum",
            )
        finally:
            os.environ.pop(VARIAVEL, None)
            destino.unlink(missing_ok=True)

    def test_a_copia_nao_vai_por_cima_de_uma_anterior(self) -> None:
        """Modo `x`: uma copia que sobrescrevesse outra perdia a primeira."""
        self._semear()
        destino = Path(tempfile.gettempdir()) / f"kamba-0030-{uuid.uuid4().hex}.jsonl"
        destino.write_text("ja existia\n", encoding="utf-8")
        os.environ[VARIAVEL] = str(destino)
        try:
            resultado = alembic("downgrade", ANTERIOR)
            self.assertNotEqual(resultado.returncode, 0)
            self.assertEqual(destino.read_text(encoding="utf-8"), "ja existia\n")
            self.assertEqual(self.tabelas_existentes(), sorted(TABELAS))
        finally:
            os.environ.pop(VARIAVEL, None)
            destino.unlink(missing_ok=True)
