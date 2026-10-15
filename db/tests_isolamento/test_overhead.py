"""O custo da politica, medido em tres consultas — sem limiar bloqueante.

Detalhes Tecnicos do KAM-004: «medir o *overhead* da politica em 3 consultas
representativas e registar (sem limiar bloqueante)».

Este teste **mede e imprime**; nao falha por desempenho. Compara a mesma
consulta feita como `kamba_app` com contexto (com politica) e como `kamba_batch`
com o mesmo filtro escrito a mao (sem politica), sobre algumas centenas de
linhas de trinta tenants.

As duas consultas vao **sem parametros ligados**. A primeira versao passava o
tenant como parametro so na consulta sem politica, e o resultado era absurdo — a
politica saia 2 ms *mais rapida* do que nao a ter. O que se media era a volta
extra de *parse* e *describe* de uma consulta parametrizada, nao a politica. O
tenant e um UUID gerado por este teste, pelo que interpola-lo e seguro.

O que os numeros valem, dito antes de os ler: sao de uma base em `tmpfs`, com
poucas linhas, num contentor numa maquina partilhada. Servem para detectar uma
politica que deixou de usar o indice — um custo de outra ordem de grandeza — e
**nao** para orcamentar latencias de producao. A medicao que conta e a do
KAM-085 (carga), com volumes reais.
"""

from __future__ import annotations

import statistics
import time
import uuid

import ligacao
from tests_isolamento.base import ComDoisTenants, definir_contexto

TENANTS_EXTRA = 30
CANAIS_POR_TENANT = 10
REPETICOES = 60

#: (rotulo, SQL com politica — sem filtro de tenant —, SQL sem politica — com ele)
CONSULTAS = (
    (
        "canais activos do tenant",
        "SELECT id, vertical FROM platform.tenant_channels WHERE estado = 'pendente'",
        "SELECT id, vertical FROM platform.tenant_channels "
        "WHERE estado = 'pendente' AND tenant_id = '{tenant}'",
    ),
    (
        "o proprio tenant",
        "SELECT id, plano, estado FROM platform.tenants",
        "SELECT id, plano, estado FROM platform.tenants WHERE id = '{tenant}'",
    ),
    (
        "entitlement de um modulo",
        "SELECT limites, ativo FROM platform.entitlements WHERE modulo = 'catalogo'",
        "SELECT limites, ativo FROM platform.entitlements "
        "WHERE modulo = 'catalogo' AND tenant_id = '{tenant}'",
    ),
)


class TestOverhead(ComDoisTenants):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cursor = cls._batch.cursor()
        cls._extra: list[str] = []
        for _ in range(TENANTS_EXTRA):
            tenant = str(uuid.uuid4())
            cls._extra.append(tenant)
            cursor.execute(
                "INSERT INTO platform.tenants (id, tipo, nome) VALUES (%s, 'pme', 'carga')",
                (tenant,),
            )
            for _ in range(CANAIS_POR_TENANT):
                cursor.execute(
                    "INSERT INTO platform.tenant_channels (tenant_id, waba_id, "
                    "phone_number_id, channel_mode, vertical, token_ref) "
                    "VALUES (%s, 'waba-carga', %s, 'cloud_only', 'vendedor', 'ref-carga')",
                    (tenant, f"pnid-{uuid.uuid4().hex}"),
                )
            cursor.execute(
                "INSERT INTO platform.entitlements (tenant_id, modulo) "
                "VALUES (%s, 'catalogo')",
                (tenant,),
            )
        cursor.execute("ANALYZE platform.tenants")
        cursor.execute("ANALYZE platform.tenant_channels")
        cursor.execute("ANALYZE platform.entitlements")

    @classmethod
    def tearDownClass(cls) -> None:
        cursor = cls._batch.cursor()
        for tabela, coluna in (
            ("entitlements", "tenant_id"),
            ("tenant_channels", "tenant_id"),
            ("tenants", "id"),
        ):
            cursor.execute(
                f"DELETE FROM platform.{tabela} WHERE {coluna} = ANY(%s::uuid[])",
                (cls._extra,),
            )
        super().tearDownClass()

    @staticmethod
    def _mediana_ms(cursor, sql: str) -> float:
        tempos = []
        for _ in range(REPETICOES):
            inicio = time.perf_counter()
            cursor.execute(sql)
            cursor.fetchall()
            tempos.append((time.perf_counter() - inicio) * 1000)
        return statistics.median(tempos)

    def test_mede_e_regista(self) -> None:
        alvo = self._extra[0]
        com = ligacao.ligar("app")
        sem = ligacao.ligar("batch")
        try:
            cursor_com = com.cursor()
            definir_contexto(cursor_com, alvo)
            cursor_sem = sem.cursor()
            print()
            print(
                f"    overhead da politica tenant_iso — {TENANTS_EXTRA + 2} tenants, "
                f"{TENANTS_EXTRA * CANAIS_POR_TENANT + 2} canais, mediana de "
                f"{REPETICOES} execucoes:"
            )
            for rotulo, sql_com, modelo_sem in CONSULTAS:
                sql_sem = modelo_sem.format(tenant=str(uuid.UUID(alvo)))
                # A mesma resposta pelas duas vias: sem isto os tempos nao se comparam.
                cursor_com.execute(sql_com)
                pela_politica = sorted(map(tuple, cursor_com.fetchall()), key=str)
                cursor_sem.execute(sql_sem)
                pelo_filtro = sorted(map(tuple, cursor_sem.fetchall()), key=str)
                self.assertEqual(pela_politica, pelo_filtro, rotulo)
                self.assertTrue(pela_politica, rotulo)

                ms_com = self._mediana_ms(cursor_com, sql_com)
                ms_sem = self._mediana_ms(cursor_sem, sql_sem)
                print(
                    f"      {rotulo:<28} com politica {ms_com:6.2f} ms   "
                    f"sem politica {ms_sem:6.2f} ms   diferenca {ms_com - ms_sem:+6.2f} ms"
                )
        finally:
            com.rollback()
            sem.rollback()
            com.close()
            sem.close()

    def test_a_politica_usa_o_indice_por_tenant(self) -> None:
        """O que a medicao acima nao distingue com poucas linhas: o plano.

        Com `enable_seqscan` desligado o planeador so recorre a varrimento
        sequencial se nao houver indice que sirva; se a politica nao pudesse
        usar o indice `(tenant_id, estado)`, o plano mostrava-o.
        """
        conexao = self.ligar("app")
        cursor = conexao.cursor()
        definir_contexto(cursor, self._extra[0])
        cursor.execute("SET LOCAL enable_seqscan = off")
        cursor.execute(
            "EXPLAIN SELECT id FROM platform.tenant_channels WHERE estado = 'pendente'"
        )
        plano = "\n".join(linha[0] for linha in cursor.fetchall())
        self.assertIn("tenant_channels_tenant_estado_idx", plano)
        self.assertNotIn("Seq Scan", plano)
