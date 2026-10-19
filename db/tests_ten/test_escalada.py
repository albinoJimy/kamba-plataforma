"""Um tenant contra si proprio: as portas que a revisao adversarial mediu.

Este ficheiro existe porque o KAM-009 **reprovou**. Tres criticos, e os tres
sao a mesma frase: *um tenant decide o proprio tecto*. O ticket foi escrito
para fechar essa frase por um verbo — `UPDATE` em `tenants.plano` e em
`entitlements(limites, ativo)` — e deixou-a aberta por outros tres.

O que faz destes testes outra coisa dos do `test_isolamento.py`: ali o atacante
e **outro** tenant, e quem o para e a RLS. Aqui o atacante e **o proprio**, com
o seu proprio contexto, sobre as suas proprias linhas. A RLS nunca o podia
parar: as linhas sao dele. O que o para e o privilegio que nao existe e o
trigger que recusa.

Cada teste tem, por extenso, a sequencia que o revisor mediu. Nao sao casos
hipoteticos: sao transcricoes.
"""

from __future__ import annotations

import unittest

from tests.base import PRIVILEGIO_INSUFICIENTE, VIOLACAO_DE_CHECK
from tests_ten.base import CHAVE, CHAVE_DE_DINHEIRO, ComUso


class TestNaoCriaOProprioEntitlement(ComUso):
    """C2: `kamba_app` mantinha `INSERT` em `entitlements`.

    A sequencia medida:

        ten_consumir(valor_max_pedido_minor, 500 000 000) -> [False, 0, False, None]
        INSERT ... ('auto', '{"valor_max_pedido_minor": 900000000000}', true) -> PASSA
        ten_consumir(valor_max_pedido_minor, 500 000 000) -> [True, 500000000, ...]

    A `0007` revogava o `UPDATE` e deixava o `INSERT` da `0001` de pe. Com
    `WITH CHECK (tenant_id = app.tenant_id)` a politica **autoriza** a linha:
    e a dele. Nao e preciso subir o proprio tecto se se pode criar um — e a
    regra do minimo entre modulos nao protege nada quando a linha nova e a
    unica que declara a chave.
    """

    def test_sem_entitlement_nega_e_continua_a_negar(self) -> None:
        tenant = self.criar_tenant()
        antes = self.consumir(
            tenant, chave=CHAVE_DE_DINHEIRO, quantidade=500_000_000,
            idempotency_key="antes",
        )
        self.assertFalse(antes.aceite)
        self.assertIsNone(antes.limite)

        cursor = self.cursor_app(tenant)
        self.assertErroSql(
            PRIVILEGIO_INSUFICIENTE,
            cursor,
            "INSERT INTO platform.entitlements (tenant_id, modulo, limites, ativo) "
            "VALUES (%s::uuid, 'auto', '{\"valor_max_pedido_minor\": 900000000000}'::jsonb, true)",
            (tenant,),
        )

        depois = self.consumir(
            tenant, chave=CHAVE_DE_DINHEIRO, quantidade=500_000_000,
            idempotency_key="depois",
        )
        self.assertFalse(depois.aceite, "o tenant criou o proprio tecto")
        self.assertIsNone(depois.limite)
        self.assertEqual(self.periodos(tenant), [])

    def test_a_retaguarda_e_que_provisiona(self) -> None:
        """O controlo positivo: o caminho legitimo tem de continuar aberto."""
        tenant = self.criar_tenant()
        self.dar_entitlement(tenant, {CHAVE_DE_DINHEIRO: 900_000_000}, modulo="auto")
        consumo = self.consumir(
            tenant, chave=CHAVE_DE_DINHEIRO, quantidade=500_000_000,
            idempotency_key="k",
        )
        self.assertTrue(consumo.aceite)
        self.assertEqual(int(consumo.limite), 900_000_000)


class TestNaoZeraOProprioContador(ComUso):
    """C3: `GRANT UPDATE (valor, actualizado_at)` nao diz em que direccao.

    A sequencia medida:

        consome 10 -> aceite; mais 1 -> negado (correcto)
        UPDATE platform.tenant_usage SET valor = 0 -> PASSA
        consome 10 -> aceite

    Vinte contra um tecto de dez, e repetivel. O privilegio tem de existir: a
    `ten_consumir` e `SECURITY INVOKER` e o `ON CONFLICT DO UPDATE` corre com
    os privilegios de quem chama. O que o privilegio nao sabe exprimir —
    «so sobe» — exprime-o o trigger `tenant_usage_so_sobe`, pelo padrao que a
    `0006` ja usou para o `audit_log`.
    """

    def test_o_contador_nao_desce(self) -> None:
        tenant = self.tenant_com_limite(10)
        self.assertTrue(self.consumir(tenant, quantidade=10, idempotency_key="a").aceite)
        self.assertFalse(self.consumir(tenant, quantidade=1, idempotency_key="b").aceite)

        cursor = self.cursor_app(tenant)
        for instrucao in (
            "UPDATE platform.tenant_usage SET valor = 0",
            "UPDATE platform.tenant_usage SET valor = valor - 1",
            "UPDATE platform.tenant_usage SET valor = 9, actualizado_at = now()",
        ):
            with self.subTest(instrucao=instrucao):
                self.assertErroSql(VIOLACAO_DE_CHECK, cursor, instrucao)

        self.assertEqual(self.uso(tenant), 10)
        self.assertFalse(
            self.consumir(tenant, quantidade=10, idempotency_key="c").aceite,
            "o contador foi reposto e o tecto deixou de valer",
        )

    def test_o_trigger_dispara_sempre_e_nao_so_na_sessao_normal(self) -> None:
        """`ENABLE ALWAYS`, pela razao da `0006`.

        Com `ENABLE` simples, o trigger nao dispara em sessoes de replica
        (`session_replication_role = 'replica'`), e a propriedade deixava de
        valer exactamente onde nao ha ninguem a olhar. O catalogo guarda
        `'A'` para `ALWAYS` e `'O'` para a omissao.
        """
        self.semente.execute(
            "SELECT t.tgenabled FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
            " WHERE c.relname = 'tenant_usage' AND t.tgname = 'tenant_usage_so_sobe'"
        )
        linha = self.semente.fetchone()
        self.assertIsNotNone(linha, "o contador nao tem o trigger `tenant_usage_so_sobe`")
        self.assertEqual(str(linha[0]), "A")

    def test_o_contador_sobe_pelo_caminho_normal(self) -> None:
        """O controlo positivo: o trigger nao pode fechar o que a funcao faz."""
        tenant = self.tenant_com_limite(10)
        self.assertTrue(self.consumir(tenant, quantidade=4, idempotency_key="a").aceite)
        segunda = self.consumir(tenant, quantidade=4, idempotency_key="b")
        self.assertTrue(segunda.aceite)
        self.assertEqual(int(segunda.valor), 8)

    def test_a_linha_nao_muda_de_conta(self) -> None:
        """Mover a linha apaga o consumo na mesma, levando-o para outra conta.

        So o `kamba_batch` la chega — a aplicacao tem `UPDATE` em duas
        colunas e nenhuma delas e chave —, e esta aqui porque a propriedade e
        da tabela e nao do papel.
        """
        a = self.tenant_com_limite(10)
        b = self.tenant_com_limite(10)
        self.assertTrue(self.consumir(a, quantidade=10, idempotency_key="k").aceite)

        cursor = self.ligar("batch").cursor()
        for instrucao, argumentos in (
            ("UPDATE platform.tenant_usage SET tenant_id = %s WHERE tenant_id = %s",
             (b, a)),
            ("UPDATE platform.tenant_usage SET chave_limite = 'outra' WHERE tenant_id = %s",
             (a,)),
            # `date_trunc` para a data continuar a ser um primeiro dia de mes:
            # com uma data a meio do mes era o `CHECK` da coluna a recusar, e
            # o teste passava sem o trigger existir.
            ("UPDATE platform.tenant_usage "
             "   SET periodo = date_trunc('month', periodo + 40)::date "
             " WHERE tenant_id = %s", (a,)),
        ):
            with self.subTest(instrucao=instrucao.split(" SET ")[1][:30]):
                self.assertErroSql(
                    VIOLACAO_DE_CHECK, cursor, instrucao, argumentos
                )


class TestNaoRetiraACondicaoDoCriterio2(ComUso):
    """M6: o tenant `suspenso` que se reactiva.

    Medido: `UPDATE platform.tenants SET estado = 'ativo'` com o proprio
    contexto **passa**, e o consumo seguinte e aceite. O criterio 2 manda
    negar `onboarding`, `suspenso` e `encerrado`; o sujeito da condicao nao
    pode ser quem a retira.

    A `ten_consumir` **nao** le o estado do tenant — quem o le e o
    `checkEntitlement` das bibliotecas, pelo `SQL_ENTITLEMENT`. O que se prova
    aqui e o privilegio, que e onde a porta estava.
    """

    def test_a_aplicacao_nao_altera_o_proprio_estado(self) -> None:
        tenant = self.criar_tenant()
        self.semente.execute(
            "UPDATE platform.tenants SET estado = 'suspenso' WHERE id = %s", (tenant,)
        )
        cursor = self.cursor_app(tenant)
        for estado in ("ativo", "onboarding", "restrito"):
            with self.subTest(estado=estado):
                self.assertErroSql(
                    PRIVILEGIO_INSUFICIENTE,
                    cursor,
                    "UPDATE platform.tenants SET estado = %s WHERE id = %s",
                    (estado, tenant),
                )
        self.semente.execute(
            "SELECT estado FROM platform.tenants WHERE id = %s", (tenant,)
        )
        self.assertEqual(str(self.semente.fetchone()[0]), "suspenso")

    def test_continua_a_alterar_o_que_e_dela(self) -> None:
        """O controlo positivo: o perfil do tenant nao ficou congelado."""
        tenant = self.criar_tenant()
        cursor = self.cursor_app(tenant)
        cursor.execute(
            "UPDATE platform.tenants SET nome = 'Nome novo', zona = 'luanda' "
            " WHERE id = %s",
            (tenant,),
        )
        self.assertEqual(cursor.rowcount, 1)


if __name__ == "__main__":
    unittest.main()
