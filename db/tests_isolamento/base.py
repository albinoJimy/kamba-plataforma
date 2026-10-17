"""Base da suite de isolamento: dois tenants semeados, confirmados e apagados no fim."""

from __future__ import annotations

import uuid

import ligacao
from tests.base import PRIVILEGIO_INSUFICIENTE, ComBase, sqlstate
from tests_isolamento import catalogo, sementes


def definir_contexto(cursor, tenant_id: str | None) -> None:
    """`SET LOCAL app.tenant_id` (ou limpa-o, com `None`)."""
    cursor.execute(
        "SELECT set_config('app.tenant_id', %s, true)", (tenant_id or "",)
    )
    cursor.fetchone()


class ComDoisTenants(ComBase):
    """A e B, com canarios unicos em todas as tabelas isoladas.

    Semeados uma vez por classe e confirmados — os testes leem noutras
    ligacoes e com outros papeis, e nao veriam linhas por confirmar. Cada
    tabela e semeada pelo papel que a sua receita nomeia: `kamba_batch` onde
    ele tem privilegios, o administrador da instancia nas tabelas de identidade
    (KAM-008), em que `kamba_batch` nao toca. Nenhum teste desta suite confirma
    o que escreve.
    """

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls._semeadores = {}
        cursores = {}
        for identidade in sementes.SEMEADORES:
            conexao = ligacao.ligar(identidade)
            conexao.autocommit = True
            cls._semeadores[identidade] = conexao
            cursores[identidade] = conexao.cursor()
            cursores[identidade].execute("SET lock_timeout = '15s'")
        cls._batch = cls._semeadores["batch"]
        cls._cursores = cursores
        sementes.registar_versao_de_chave(cursores["admin"])
        cls.a = sementes.semear_tenant(cursores, "a")
        cls.b = sementes.semear_tenant(cursores, "b")
        cls.tabelas = catalogo.tabelas_isoladas(cursores["batch"])

    @classmethod
    def tearDownClass(cls) -> None:
        for tenant in (cls.a, cls.b):
            sementes.apagar_tenant(cls._cursores, tenant.id)
        sementes.retirar_versao_de_chave(cls._cursores["admin"])
        for conexao in cls._semeadores.values():
            conexao.close()
        super().tearDownClass()

    def cursor_de(self, papel: str, tenant_id: str | None = None):
        """Cursor da identidade pedida, com o contexto pedido (ou sem nenhum)."""
        cursor = self.ligar(papel).cursor()
        if tenant_id is not None:
            definir_contexto(cursor, tenant_id)
        return cursor

    def cursor_app(self, tenant_id: str | None = None):
        """Cursor de `kamba_app`, com o contexto pedido (ou sem nenhum)."""
        return self.cursor_de("app", tenant_id)

    def por_tabela(self):
        """(schema, tabela, coluna de isolamento, receita), do catalogo.

        Quem itera abre o seu `subTest`: assim uma tabela que falhe nao esconde
        as seguintes. A receita diz com que papel a tabela se ataca
        (`receita.papel`): o que a consegue ler.

        **So as que o papel le.** Uma tabela com `leitura_do_papel=False` nao
        entra aqui: o papel nao tem `SELECT` nela, e uma leitura cruzada que
        rebenta com `42501` nao prova isolamento nenhum. O que ha a provar
        nessas esta no `por_tabela_sem_leitura()`, e e mais forte.
        """
        return [
            (schema, tabela, coluna, sementes.RECEITAS[(schema, tabela)])
            for schema, tabela, coluna in self.tabelas
            if sementes.RECEITAS[(schema, tabela)].leitura_do_papel
        ]

    def por_tabela_sem_leitura(self):
        """As tabelas que o papel escreve e **nao** le."""
        return [
            (schema, tabela, coluna, sementes.RECEITAS[(schema, tabela)])
            for schema, tabela, coluna in self.tabelas
            if not sementes.RECEITAS[(schema, tabela)].leitura_do_papel
        ]

    def por_tabela_que_escreve(self):
        """As tabelas em que o papel **insere**, leia-as ou nao.

        Ler e escrever sao duas dimensoes, e os testes de escrita cruzada
        precisam da segunda. Filtrar a escrita a partir do `por_tabela()` —
        que ja tira as que o papel nao le — tirava a `events_dlq` do `WITH
        CHECK` **e** do `SELECT`, deixando a tabela sem teste de isolamento
        nenhum na escrita. O `INSERT` nao precisa de `SELECT` para ser
        recusado pela politica, pelo que nao ha razao para as juntar.
        """
        return [
            (schema, tabela, coluna, sementes.RECEITAS[(schema, tabela)])
            for schema, tabela, coluna in self.tabelas
            if sementes.RECEITAS[(schema, tabela)].escrita_do_papel
        ]

    def por_tabela_sem_escrita(self):
        """As tabelas em que nenhum papel sujeito a RLS insere."""
        return [
            (schema, tabela, coluna, sementes.RECEITAS[(schema, tabela)])
            for schema, tabela, coluna in self.tabelas
            if not sementes.RECEITAS[(schema, tabela)].escrita_do_papel
        ]

    def _inserir_tem_de_falhar(self, cursor, receita, tenant_id: str) -> None:
        """A receita de insercao tem de ser recusada **pela politica**.

        Confere-se o SQLSTATE e o texto: `42501` e tambem o codigo de um
        privilegio em falta, e um teste que aceitasse qualquer `42501` passava
        se alguem tirasse o `INSERT` a `kamba_app` — pela razao errada.
        """
        import pg8000.dbapi

        cursor.execute("SAVEPOINT caso_negativo")
        try:
            with self.assertRaises(pg8000.dbapi.DatabaseError) as capturado:
                receita.inserir(cursor, tenant_id, f"canario_intruso_{uuid.uuid4().hex}")
        finally:
            cursor.execute("ROLLBACK TO SAVEPOINT caso_negativo")
        self.assertEqual(sqlstate(capturado.exception), PRIVILEGIO_INSUFICIENTE)
        self.assertIn("row-level security", str(capturado.exception))

    def _inserir_sem_privilegio(self, cursor, receita, tenant_id: str) -> None:
        """A receita tem de ser recusada **pelo privilegio**, nao pela politica.

        O inverso de `_inserir_tem_de_falhar`, e para as tabelas em que nenhum
        papel sujeito a RLS escreve (`Receita.escrita_do_papel = False`). O
        mesmo `42501` com outro texto: aceitar qualquer `42501` aqui passava se
        alguem desse `INSERT` ao papel e a politica o recusasse — o que e uma
        protecao mais fraca do que a que esta tabela tem hoje.
        """
        import pg8000.dbapi

        cursor.execute("SAVEPOINT caso_negativo")
        try:
            with self.assertRaises(pg8000.dbapi.DatabaseError) as capturado:
                receita.inserir(cursor, tenant_id, f"canario_intruso_{uuid.uuid4().hex}")
        finally:
            cursor.execute("ROLLBACK TO SAVEPOINT caso_negativo")
        self.assertEqual(sqlstate(capturado.exception), PRIVILEGIO_INSUFICIENTE)
        self.assertIn("permission denied", str(capturado.exception))
        self.assertNotIn("row-level security", str(capturado.exception))
