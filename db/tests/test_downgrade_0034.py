"""O `downgrade` da revisao `0034` desfaz cada objecto, pelo nome (KAM-091).

## Porque e que o ciclo do *gate* 8 nao basta

O `test_upgrade_downgrade_upgrade` de `test_migracao.py` prova que a cadeia
encaixa: desce ate `base`, volta a `head` e compara o conjunto de tabelas com o
`TABELAS`. **Passa inteiro sobre um `downgrade` que se esqueca de uma coluna, de
um `CHECK` ou de uma politica** — o `upgrade` seguinte volta a cria-los, e a
unica coisa que o ciclo compara e a lista de nomes de tabela.

Este ficheiro afirma **cada objecto pelo nome**: a tabela, as dez colunas, os
oito `CHECK`, a chave primaria, o indice e a politica.

## A sonda positiva nao e cerimonia

Cada familia de objectos verifica-se **duas** vezes: primeiro em `head` a exigir
**presenca**, e so depois a exigir ausencia. A razao e medida e vale para toda a
consulta de catalogo escrita a mao: **uma consulta errada devolve zero linhas
dos dois lados**. Um nome de tabela mal escrito, um esquema errado, um
`pg_constraint` onde devia estar um `pg_indexes` — todos dao a mesma lista vazia
depois do `downgrade`, e um ensaio que so verifique a ausencia fica verde sem
ter medido nada. O ensaio da presenca e o que torna os outros interpretaveis.

## E pergunta-se ao `pg_constraint`, nao ao `pg_indexes`

Um `CHECK` aparece **so** no `pg_constraint`. A chave primaria aparece nos dois
— cria um indice unico com o nome dela —, mas pergunta-se tambem ao
`pg_constraint`, porque e la que ela e uma restricao e nao so um indice. O
`provisioning_step_tenant_idx` nao serve restricao nenhuma e pergunta-se ao
`pg_indexes`, que e o unico onde existe.

**Esta revisao nao tem `UNIQUE` separada, e isso e desenho e nao omissao:** a
`UNIQUE(onboarding_id, step)` do contrato **e** a chave primaria, pelo que nao
ha um `_uq` ao lado dela a afirmar o mesmo par duas vezes.

## Nenhuma funcao, nenhum *trigger* e nenhuma FK

A revisao nao cria nenhum dos tres, pelo que nao ha ensaio para eles — e a
ausencia e afirmada: o `test_em_head_a_revisao_nao_traz_funcao_trigger_nem_fk`
mede-o contra o catalogo, porque «esta revisao nao cria X» e uma afirmacao sobre
o mundo como qualquer outra. A FK em particular **nao pode** existir: o passo 1
da saga (`tenant_e_caso`) e que escreve a linha de `platform.tenants`, e uma FK
daqui para la tornava o proprio passo 1 impossivel.
"""

from __future__ import annotations

import unittest

import bootstrap
import ligacao
from tests.base import alembic_ok, em_head, exigir_base_descartavel

#: A revisao anterior. O `downgrade` desta volta aqui.
#:
#: **E a `0033`, e confirmou-se na integracao.** Quando o KAM-091 fundiu, a
#: `0033` do KAM-045 ainda estava num PR aberto e esta revisao nao existia.
#: Esta constante e a `down_revision` da revisao andam **juntas**:
#: desencontradas, este ensaio desce uma revisao a mais ou a menos e afirma a
#: ausencia de objectos que a outra revisao criou.
ANTERIOR = "0033"

#: A unica tabela que a revisao cria.
TABELA = "provisioning_step"

#: As **dez** colunas, uma a uma. O ciclo do *gate* 8 nao as ve: um
#: `downgrade` que largasse a tabela e deixasse uma coluna atras era impossivel
#: aqui (as colunas caem com ela), mas um `downgrade` **futuro** que passasse a
#: alterar esta tabela em vez de a largar ja o seria — e esta lista e o que o
#: apanha.
COLUNAS = (
    "onboarding_id",
    "tenant_id",
    "step",
    "status",
    "attempt",
    "external_id",
    "error_code",
    "status_de_espera",
    "criado_at",
    "atualizado_at",
)

#: As **nove** restricoes: os oito `CHECK` e a chave primaria.
#:
#: A chave primaria **e** a `UNIQUE(onboarding_id, step)` do contrato, pelo que
#: nao ha um `_uq` ao lado dela — ver a nota do modulo.
RESTRICOES = (
    "provisioning_step_pkey",
    "provisioning_step_step_ck",
    "provisioning_step_status_ck",
    "provisioning_step_espera_ck",
    "provisioning_step_attempt_ck",
    "provisioning_step_error_code_ck",
    "provisioning_step_external_id_ck",
    "provisioning_step_falha_exige_codigo_ck",
    "provisioning_step_concluido_limpo_ck",
)

#: O unico indice que nao serve restricao nenhuma. Comeca pelo `tenant_id`
#: porque a chave primaria nao comeca, e e isso que a convencao do
#: `test_catalogo.py` exige de toda a tabela com a coluna.
INDICES = ("provisioning_step_tenant_idx",)

#: A politica. O `db/rls.py` e o unico sitio onde o nome se escreve.
POLITICA = "tenant_iso"


class TestDowngradeDa0034(unittest.TestCase):
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

    def tearDown(self) -> None:
        try:
            if not em_head():
                alembic_ok("upgrade", "head")
        finally:
            self.conexao.close()

    # -------------------------------------------------------------- auxiliares

    def _um(self, sql: str, parametros: tuple) -> list[str]:
        self.cursor.execute(sql, parametros)
        return sorted(str(linha[0]) for linha in self.cursor.fetchall())

    def tabelas(self) -> list[str]:
        return self._um(
            "SELECT tablename::text FROM pg_tables "
            " WHERE schemaname = 'platform' AND tablename = %s",
            (TABELA,),
        )

    def colunas(self) -> list[str]:
        return self._um(
            "SELECT column_name::text FROM information_schema.columns "
            " WHERE table_schema = 'platform' AND table_name = %s",
            (TABELA,),
        )

    def restricoes(self) -> list[str]:
        # Ao `pg_constraint` e nao ao `pg_indexes`: um `CHECK` aparece **so**
        # aqui. Ver a nota do modulo.
        return self._um(
            "SELECT c.conname::text FROM pg_constraint c "
            "  JOIN pg_namespace n ON n.oid = c.connamespace "
            " WHERE n.nspname = 'platform' AND c.conname = ANY(%s)",
            (list(RESTRICOES),),
        )

    def indices(self) -> list[str]:
        return self._um(
            "SELECT indexname::text FROM pg_indexes "
            " WHERE schemaname = 'platform' AND indexname = ANY(%s)",
            (list(INDICES),),
        )

    def politicas(self) -> list[str]:
        return self._um(
            "SELECT policyname::text FROM pg_policies "
            " WHERE schemaname = 'platform' AND tablename = %s",
            (TABELA,),
        )

    def rls_do_passo(self) -> tuple[bool, bool] | None:
        """O par `(ENABLE, FORCE)` da tabela, ou `None` se ela nao existir."""
        self.cursor.execute(
            "SELECT c.relrowsecurity, c.relforcerowsecurity FROM pg_class c "
            "  JOIN pg_namespace n ON n.oid = c.relnamespace "
            " WHERE n.nspname = 'platform' AND c.relname = %s",
            (TABELA,),
        )
        linha = self.cursor.fetchone()
        return None if linha is None else (bool(linha[0]), bool(linha[1]))

    def chaves_estrangeiras(self) -> list[str]:
        return self._um(
            "SELECT c.conname::text FROM pg_constraint c "
            "  JOIN pg_class t ON t.oid = c.conrelid "
            "  JOIN pg_namespace n ON n.oid = t.relnamespace "
            " WHERE n.nspname = 'platform' AND t.relname = %s "
            "   AND c.contype = 'f'",
            (TABELA,),
        )

    def funcoes_e_triggers(self) -> tuple[list[str], list[str]]:
        funcoes = self._um(
            "SELECT p.proname::text FROM pg_proc p "
            "  JOIN pg_namespace n ON n.oid = p.pronamespace "
            " WHERE n.nspname = 'platform' AND p.proname LIKE %s",
            ("provisioning%",),
        )
        triggers = self._um(
            "SELECT t.tgname::text FROM pg_trigger t "
            "  JOIN pg_class c ON c.oid = t.tgrelid "
            "  JOIN pg_namespace n ON n.oid = c.relnamespace "
            " WHERE n.nspname = 'platform' AND NOT t.tgisinternal "
            "   AND c.relname = %s",
            (TABELA,),
        )
        return funcoes, triggers

    # ----------------------------------------------------------------- ensaios

    def test_em_head_os_objectos_existem(self) -> None:
        """**A sonda positiva.** Sem ela, os ensaios de ausencia nao se leem.

        Ver a nota do modulo: uma consulta de catalogo errada devolve zero dos
        dois lados, e um ensaio que so verifique a ausencia fica verde sem ter
        medido nada. Este ensaio e o que torna os outros interpretaveis.
        """
        self.assertEqual(self.tabelas(), [TABELA])
        self.assertEqual(self.colunas(), sorted(COLUNAS))
        self.assertEqual(self.restricoes(), sorted(RESTRICOES))
        self.assertEqual(self.indices(), sorted(INDICES))
        self.assertEqual(self.politicas(), [POLITICA])
        self.assertEqual(
            self.rls_do_passo(),
            (True, True),
            "ENABLE e FORCE, que e o que o X-05 do gate 6 exige",
        )

    def test_em_head_a_revisao_nao_traz_funcao_trigger_nem_fk(self) -> None:
        """«Esta revisao nao cria X» e uma afirmacao, e mede-se.

        A FK em particular **nao pode** existir: o passo 1 da saga
        (`tenant_e_caso`) e que escreve a linha de `platform.tenants`, pelo que
        uma FK daqui para la tornava o proprio passo 1 impossivel. Um ticket
        futuro que a acrescentasse por parecer que falta parte este ensaio, que
        e onde a razao esta escrita.
        """
        funcoes, triggers = self.funcoes_e_triggers()
        self.assertEqual(funcoes, [], "a revisao nao cria funcao nenhuma")
        self.assertEqual(triggers, [], "nem *trigger*: o atualizado_at e do modulo")
        self.assertEqual(
            self.chaves_estrangeiras(),
            [],
            "sem FK para tenants: o passo 1 da saga e que escreve essa linha",
        )

    def test_o_downgrade_leva_todos_os_objectos_pelo_nome(self) -> None:
        """Desce **uma** revisao e exige a ausencia de cada objecto, pelo nome."""
        alembic_ok("downgrade", ANTERIOR)

        self.assertEqual(self.tabelas(), [], "a tabela cai")
        self.assertEqual(self.colunas(), [], "e as dez colunas com ela")
        self.assertEqual(
            self.restricoes(),
            [],
            "os oito CHECK e a chave primaria caem com a tabela, e este ensaio "
            "e o que o afirma pelo nome — o ciclo do gate 8 compara listas de "
            "tabelas e nao veria um que ficasse",
        )
        self.assertEqual(self.indices(), [], "e o indice do tenant")
        self.assertEqual(
            self.politicas(),
            [],
            "a politica sai pelo rls.disable_tenant_rls e nao por efeito do "
            "DROP TABLE: e o que o ensaio de mutacao do canon_lint exige",
        )
        self.assertIsNone(
            self.rls_do_passo(), "sem tabela nao ha ENABLE nem FORCE para ler"
        )

    def test_o_upgrade_seguinte_repoe_todos_os_objectos(self) -> None:
        """Desce, confirma a pre-condicao, e volta a subir.

        A confirmacao do meio nao e repeticao do ensaio anterior: sem ela, um
        `downgrade` que nao fizesse nada deixava este ensaio verde a medir o
        estado que nunca saiu de `head`.
        """
        alembic_ok("downgrade", ANTERIOR)
        self.assertEqual(self.tabelas(), [], "pre-condicao: a tabela saiu")

        alembic_ok("upgrade", "head")

        self.assertEqual(self.tabelas(), [TABELA])
        self.assertEqual(self.colunas(), sorted(COLUNAS))
        self.assertEqual(self.restricoes(), sorted(RESTRICOES))
        self.assertEqual(self.indices(), sorted(INDICES))
        self.assertEqual(self.politicas(), [POLITICA])
        self.assertEqual(self.rls_do_passo(), (True, True))

    def test_o_downgrade_desce_com_passos_escritos(self) -> None:
        """Com linhas na tabela, o `downgrade` desce.

        Um `DROP TABLE` sem `CASCADE` nao se importa com as linhas, mas
        importa-se com o que esteja pendurado nela — e esta tabela e o fim de
        uma cadeia que nao existe ainda (nenhuma FK aponta para ela). O ensaio
        fixa isso: se um ticket futuro puser uma FK a apontar para o
        `provisioning_step`, este `downgrade` passa a falhar, e e aqui que se ve
        porque.

        A linha semeia-se com o `admin`, que e o **superutilizador** da
        instancia e por isso nao esta sujeito a RLS. Com o `kamba_migrator` — o
        dono das tabelas — nao passava: a politica e `FORCE`, que vincula
        tambem o dono, e um `INSERT` sem `app.tenant_id` era recusado pelo
        `WITH CHECK`.
        """
        onboarding = "11111111-1111-4111-8111-111111111111"
        tenant = "22222222-2222-4222-8222-222222222222"
        # O administrador escreve sem contexto de tenant, que e a mesma escolha
        # do ensaio equivalente da `0033`.
        self.cursor.execute(
            "INSERT INTO platform.provisioning_step "
            "(onboarding_id, tenant_id, step, status, attempt) "
            "VALUES (%s, %s, 'tenant_e_caso', 'concluido', 1)",
            (onboarding, tenant),
        )
        self.cursor.execute("SELECT count(*) FROM platform.provisioning_step")
        self.assertEqual(
            self.cursor.fetchone()[0], 1, "pre-condicao: ha uma linha escrita"
        )

        alembic_ok("downgrade", ANTERIOR)

        self.assertEqual(self.tabelas(), [], "a tabela cai com as linhas dentro")
