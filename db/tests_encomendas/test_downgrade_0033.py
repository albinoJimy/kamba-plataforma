"""O `downgrade` da `0033`: afirma-se sobre os **objectos**, nao sobre a cadeia.

A caixa «Migracoes reversiveis: `downgrade` testado» da Definition of Done do
KAM-045 nao se cumpre com um `alembic downgrade` que devolva zero. O ciclo
`upgrade -> downgrade -> upgrade` ja corre no *gate* 8
(`tests/test_migracao.TestCiclo`) e o que ele prova e que a **cadeia** encaixa:
que o Alembic desce e sobe sem levantar. Um `downgrade` que largasse a tabela e
se esquecesse das duas colunas da `offer_terms`, ou que deixasse as duas funcoes
no catalogo, passava aquele ciclo inteiro.

O que esta classe mede e outra coisa: **que cada objecto que o `upgrade` cria
deixa de existir, pelo nome, e volta a existir no `upgrade` seguinte.**

```text
em head                     os vinte e dois objectos existem   <- a SONDA POSITIVA
depois do downgrade         nenhum existe
depois de novo upgrade      os vinte e dois voltam
```

## A sonda positiva nao e cerimonia: sem ela as outras ficam verdes a ler zero

E a armadilha desta familia de ensaios, e e silenciosa. Se uma consulta de
catalogo estiver errada — esquema trocado, nome com um caracter a mais, a
coluna `conname` onde devia estar `relname` — ela devolve **zero linhas em head
e zero depois do `downgrade`**, e um ensaio que so verifique «depois do
`downgrade` esta vazio» fica verde sem ter medido nada.

Por isso cada pergunta deste ficheiro e feita **primeiro em head, a exigir
presenca**, e so depois a exigir ausencia. O `test_em_head_os_objectos_existem`
e o ensaio que torna os outros interpretaveis, e se ele falhar os outros nao se
leem.

## As restricoes perguntam-se ao `pg_constraint`, nao ao `pg_indexes`

**Sao catalogos diferentes, e confundi-los deixa metade das restricoes sem
medicao.** Um `UNIQUE` e uma `PRIMARY KEY` aparecem nos dois — a restricao no
`pg_constraint` e o indice que a serve no `pg_indexes`, com o mesmo nome —, mas
um `CHECK` e uma `FOREIGN KEY` aparecem **so** no `pg_constraint`. Esta revisao
tem onze `CHECK` e duas `FOREIGN KEY` contra uma `UNIQUE` e uma `PRIMARY KEY`:
perguntar pelo indice media **duas** de quinze e dizia «as restricoes
cairam» — e as duas sao a chave primaria e a unicidade.

Os indices que **nao** servem restricao nenhuma — os tres do varrimento e das
consultas — perguntam-se ao `pg_indexes`, que e o catalogo deles. As duas
perguntas estao separadas de proposito.

## O `downgrade` da `0033` nao perde linhas, e por isso nao tem guarda

Ao contrario da `0030`, que exige o `KAMBA_DOWNGRADE_0030_COPIA` antes de apagar
encomendas, esta revisao desce **sem variavel de autorizacao**. Nao e
esquecimento: uma reserva e um estado derivado — o que se perde ao larga-la e
reconstruivel do `orders_mirror` mais a `offer_terms`, e o que **nao** e
reconstruivel (a prova de que cada `paga` veio de um evento autenticado) vive no
`order_state_log`, que esta revisao nao toca.

O que a descida perde de facto, e fica dito, e o `stock_reservada` da
`offer_terms`: a coluna cai e com ela a conta do que estava prometido. Uma
subida nova comeca com `stock_reservada = 0` em todas as ofertas, com reservas
que ja nao existem — o que e consistente, porque a tabela que as guardava caiu
no mesmo `downgrade`.

Esta classe **nao** herda de `ComEncomendas`: controla ela propria a revisao em
que a base esta, como o `TestDowngradeDa0030`. Repoe `head` no fim, corra bem ou
mal.
"""

from __future__ import annotations

import unittest
import uuid

import bootstrap
import ligacao
from tests.base import alembic_ok, em_head, exigir_base_descartavel

#: A revisao anterior. O `downgrade` desta volta aqui.
#:
#: **E a `0032` — a renumeracao fez-se na integracao, como estava previsto.** A
#: `0032` estava tomada pelo KAM-054 num PR aberto quando este ticket comecou, e
#: a cadeia escrita era `0031 -> 0033`; o KAM-054 fundiu primeiro (`8f8ac19`,
#: #128) e a cadeia passou a `0032 -> 0033`. Esta constante e a `down_revision`
#: da revisao andam **juntas**: desencontradas, este ensaio desce uma revisao a
#: mais ou a menos e afirma a ausencia de objectos que a outra revisao criou.
ANTERIOR = "0032"

#: A unica tabela que a revisao cria.
TABELA = "stock_reservations"

#: As duas colunas que ela acrescenta a `offer_terms`.
COLUNAS_DA_OFERTA = ("stock_quantidade", "stock_reservada")

#: A funcao. **Nao e `CREATE OR REPLACE`**: nasce nesta revisao, pelo que o
#: `downgrade` apaga-a em vez de repor uma versao anterior — que nao existe.
#:
#: A distincao importa nos dois sentidos, e e por isso que esta escrita: uma
#: funcao **reposta** onde devia ser apagada deixava a revisao anterior com uma
#: funcao que nao e dela; uma **apagada** onde devia ser reposta deixava a
#: anterior sem a dela, e o `downgrade` dessa falhava a procurar o que ja nao
#: existe. Aqui e o primeiro caso, e esta medido.
FUNCOES = ("stock_reserva_transicao_valida",)

#: O *trigger*, sobre a `stock_reservations`.
#:
#: **Nao fica pendurado sobre tabela que esta revisao nao apague**, e e o que
#: este ensaio confirma pelo nome — e sem filtrar por tabela, de proposito (ver
#: o auxiliar `triggers`). Um *trigger* desta revisao sobre a `offer_terms` —
#: que a `0028` criou e esta revisao **nao** apaga — nao impediria o `upgrade`
#: seguinte: impediria o `downgrade` da `0028`, que corre `DROP TABLE` sem
#: `CASCADE`, e a falha apareceria a cinco revisoes de distancia do defeito.
TRIGGERS = ("stock_reserva_transicao",)

#: As restricoes da `stock_reservations`, **pelo nome da restricao**. Ver a nota
#: do modulo para a razao de nao se perguntar pelo indice.
RESTRICOES_DA_RESERVA = (
    "stock_reservations_consumida_exige_instante_ck",
    "stock_reservations_encomenda_do_mesmo_tenant_fk",
    "stock_reservations_estado_ck",
    "stock_reservations_libertada_exige_motivo_ck",
    "stock_reservations_line_no_ck",
    # A `stock_reservations_linha_uq` saiu daqui com a revisao `0046` (KAM-050):
    # em `head` a unicidade e o indice parcial `stock_reservations_linha_viva_uq`,
    # que nao e restricao e por isso se pergunta ao `pg_indexes`, abaixo.
    "stock_reservations_motivo_ck",
    "stock_reservations_pkey",
    "stock_reservations_qty_ck",
    "stock_reservations_sku_ck",
    "stock_reservations_tenant_fk",
    "stock_reservations_version_ck",
)

#: As quatro restricoes que a revisao acrescenta a `offer_terms`. Estas sao as
#: que mais importam ao ensaio: caem com as colunas (`DROP COLUMN` leva os
#: `CHECK` que as mencionam), e nao por um `DROP CONSTRAINT` escrito a mao — pelo
#: que um `downgrade` que largasse as colunas e **nao** as restricoes nao e um
#: estado possivel, e um que largasse as restricoes e nao as colunas deixava
#: `offer_terms` sem a barreira da sobrevenda com a coluna ainda la.
#: **Tres e nao quatro.** O `offer_terms_stock_garantido_exige_quantidade_ck`
#: esteve aqui e saiu depois da revisao adversarial: era uma barreira
#: retroactiva sobre a tabela de outro ticket sem o caminho de escrita que a
#: satisfaz, e media-se em `Ran 63 / FAILED (failures=1, errors=34)` na suite
#: `tests_produtos`. O invariante passou para o predicado do `SQL_RESERVAR`.
RESTRICOES_DA_OFERTA = (
    "offer_terms_stock_nao_sobrevende_ck",
    "offer_terms_stock_quantidade_ck",
    "offer_terms_stock_reservada_ck",
)

#: Os quatro indices que **nao** servem restricao nenhuma. Perguntam-se ao
#: `pg_indexes`, que e o catalogo deles.
INDICES = (
    "stock_reservations_encomenda_idx",
    "stock_reservations_expira_idx",
    "stock_reservations_tenant_estado_idx",
    # O da `0046`: e unico, mas parcial, e um `UNIQUE` parcial so existe como
    # indice. Cai com a tabela no `downgrade` para `0032`, como os outros.
    "stock_reservations_linha_viva_uq",
)

#: A politica de RLS, com o nome que o `db/rls.py` fixa.
POLITICA = "tenant_iso"


class TestDowngradeDa0033(unittest.TestCase):
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

    def colunas_da_oferta(self) -> list[str]:
        return self._um(
            "SELECT column_name::text FROM information_schema.columns "
            " WHERE table_schema = 'platform' AND table_name = 'offer_terms' "
            "   AND column_name = ANY(%s)",
            (list(COLUNAS_DA_OFERTA),),
        )

    def funcoes(self) -> list[str]:
        return self._um(
            "SELECT p.proname::text FROM pg_proc p "
            "  JOIN pg_namespace n ON n.oid = p.pronamespace "
            " WHERE n.nspname = 'platform' AND p.proname = ANY(%s)",
            (list(FUNCOES),),
        )

    def triggers(self) -> list[str]:
        """Os *triggers* pelo nome, em **qualquer** tabela de `platform`.

        Sem filtro por tabela de proposito: a pergunta e «este *trigger* existe
        em algum sitio», e um filtro por `stock_reservations` nao veria um que
        tivesse ficado pendurado na `offer_terms` — que e precisamente o caso
        que a nota do `TRIGGERS` descreve.
        """
        return self._um(
            "SELECT t.tgname::text FROM pg_trigger t "
            "  JOIN pg_class c ON c.oid = t.tgrelid "
            "  JOIN pg_namespace n ON n.oid = c.relnamespace "
            " WHERE n.nspname = 'platform' AND NOT t.tgisinternal "
            "   AND t.tgname = ANY(%s)",
            (list(TRIGGERS),),
        )

    def restricoes(self, nomes: tuple[str, ...]) -> list[str]:
        """As restricoes pelo nome, do `pg_constraint`. Ver a nota do modulo."""
        return self._um(
            "SELECT c.conname::text FROM pg_constraint c "
            "  JOIN pg_namespace n ON n.oid = c.connamespace "
            " WHERE n.nspname = 'platform' AND c.conname = ANY(%s)",
            (list(nomes),),
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

    def rls_da_reserva(self) -> tuple[bool, bool] | None:
        """O par `(ENABLE, FORCE)` da tabela, ou `None` se ela nao existir."""
        self.cursor.execute(
            "SELECT c.relrowsecurity, c.relforcerowsecurity FROM pg_class c "
            "  JOIN pg_namespace n ON n.oid = c.relnamespace "
            " WHERE n.nspname = 'platform' AND c.relname = %s",
            (TABELA,),
        )
        linha = self.cursor.fetchone()
        return None if linha is None else (bool(linha[0]), bool(linha[1]))

    # ----------------------------------------------------------------- ensaios

    def test_em_head_os_objectos_existem(self) -> None:
        """**A sonda positiva.** Sem ela, os ensaios de ausencia nao se leem.

        Ver a nota do modulo: uma consulta de catalogo errada devolve zero dos
        dois lados, e um ensaio que so verifique a ausencia fica verde sem ter
        medido nada. Este ensaio e o que torna os outros interpretaveis.
        """
        self.assertEqual(self.tabelas(), [TABELA])
        self.assertEqual(self.colunas_da_oferta(), sorted(COLUNAS_DA_OFERTA))
        self.assertEqual(self.funcoes(), sorted(FUNCOES))
        self.assertEqual(self.triggers(), sorted(TRIGGERS))
        self.assertEqual(
            self.restricoes(RESTRICOES_DA_RESERVA), sorted(RESTRICOES_DA_RESERVA)
        )
        self.assertEqual(
            self.restricoes(RESTRICOES_DA_OFERTA), sorted(RESTRICOES_DA_OFERTA)
        )
        self.assertEqual(self.indices(), sorted(INDICES))
        self.assertEqual(self.politicas(), [POLITICA])
        self.assertEqual(
            self.rls_da_reserva(),
            (True, True),
            "ENABLE e FORCE, que e o que a caixa 4 da DoD pede",
        )

    def test_o_downgrade_leva_todos_os_objectos_pelo_nome(self) -> None:
        """Desce **uma** revisao e exige a ausencia de cada objecto, pelo nome."""
        alembic_ok("downgrade", ANTERIOR)

        self.assertEqual(self.tabelas(), [], "a tabela cai")
        self.assertEqual(
            self.colunas_da_oferta(),
            [],
            "e as duas colunas da offer_terms com ela: e o que um `downgrade` "
            "que so largasse a tabela deixava para tras, e o ciclo do gate 8 "
            "nao via",
        )
        self.assertEqual(
            self.funcoes(),
            [],
            "as duas funcoes nao caem com a tabela: o downgrade apaga-as",
        )
        self.assertEqual(
            self.triggers(),
            [],
            "nenhum trigger fica pendurado — nem na tabela que caiu, nem na "
            "offer_terms que ficou",
        )
        self.assertEqual(self.restricoes(RESTRICOES_DA_RESERVA), [])
        self.assertEqual(
            self.restricoes(RESTRICOES_DA_OFERTA),
            [],
            "as quatro da offer_terms caem com as colunas que restringem",
        )
        self.assertEqual(self.indices(), [])
        self.assertEqual(self.politicas(), [], "a politica tenant_iso cai")
        self.assertIsNone(self.rls_da_reserva(), "e a tabela ja nao esta la")

    def test_o_upgrade_seguinte_repoe_todos_os_objectos(self) -> None:
        """A volta: desce, sobe, e tudo volta a existir pelo nome.

        E o que distingue «o `downgrade` apaga» de «o `downgrade` apaga e a
        revisao volta a aplicar-se»: um `downgrade` que deixasse o catalogo num
        estado em que o `upgrade` falha passava o ensaio de cima inteiro.
        """
        alembic_ok("downgrade", ANTERIOR)
        self.assertEqual(self.tabelas(), [], "pre-condicao: desceu")
        alembic_ok("upgrade", "head")

        self.assertEqual(self.tabelas(), [TABELA])
        self.assertEqual(self.colunas_da_oferta(), sorted(COLUNAS_DA_OFERTA))
        self.assertEqual(self.funcoes(), sorted(FUNCOES))
        self.assertEqual(self.triggers(), sorted(TRIGGERS))
        self.assertEqual(
            self.restricoes(RESTRICOES_DA_RESERVA), sorted(RESTRICOES_DA_RESERVA)
        )
        self.assertEqual(
            self.restricoes(RESTRICOES_DA_OFERTA), sorted(RESTRICOES_DA_OFERTA)
        )
        self.assertEqual(self.indices(), sorted(INDICES))
        self.assertEqual(self.politicas(), [POLITICA])
        self.assertEqual(self.rls_da_reserva(), (True, True))

    def test_o_downgrade_desce_com_reservas_escritas(self) -> None:
        """Com linhas na tabela, o `downgrade` desce — e nao pede autorizacao.

        Ver a nota do modulo para a razao de nao haver guarda: uma reserva e
        estado derivado, e o que nao se reconstroi vive no `order_state_log`,
        que esta revisao nao toca.

        O que este ensaio impede e o oposto do da `0030`: que alguem
        acrescente uma guarda a esta revisao sem decidir que a perda importa, e
        passe a precisar de uma variavel de ambiente para descer uma revisao que
        nada perde de irreconstruivel.
        """
        tenant = str(uuid.uuid4())
        self.cursor.execute(
            "INSERT INTO platform.tenants (id, tipo, nome) "
            "VALUES (%s, 'pme', 'Loja do downgrade das reservas')",
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
            "VALUES (%s, %s, 'ik-downgrade-0033', 1000, '[]'::jsonb) RETURNING id",
            (tenant, contacto),
        )
        encomenda = str(self.cursor.fetchone()[0])
        self.cursor.execute(
            "INSERT INTO platform.offer_terms "
            "       (tenant_id, sku, nome, preco_tipo, stock_modo, "
            "        stock_quantidade, stock_reservada) "
            "VALUES (%s, 'arroz-5kg', 'Arroz 5 kg', 'sob_consulta', "
            "        'garantido', 10, 1)",
            (tenant,),
        )
        self.cursor.execute(
            "INSERT INTO platform.stock_reservations "
            "       (tenant_id, order_id, line_no, sku, qty, expira_at) "
            "VALUES (%s, %s, 0, 'arroz-5kg', 1, now() + interval '48 hours')",
            (tenant, encomenda),
        )
        self.cursor.execute("SELECT count(*) FROM platform.stock_reservations")
        self.assertEqual(int(self.cursor.fetchone()[0]), 1, "pre-condicao")

        alembic_ok("downgrade", ANTERIOR)
        self.assertEqual(self.tabelas(), [], "desceu com a linha escrita")
        self.assertEqual(self.colunas_da_oferta(), [])

        # A oferta **fica**: a `0028` e que a criou, e esta revisao nao a apaga.
        self.cursor.execute(
            "SELECT count(*) FROM platform.offer_terms WHERE tenant_id = %s",
            (tenant,),
        )
        self.assertEqual(
            int(self.cursor.fetchone()[0]),
            1,
            "a offer_terms e da 0028: o downgrade da 0033 leva-lhe as colunas, "
            "nao as linhas",
        )
