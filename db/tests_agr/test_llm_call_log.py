"""A `dat.llm_call_log` contra um PostgreSQL real (KAM-030).

    TestOEsquemaEAsColunas  o esquema `dat` e as dezesseis colunas da `0023`
    TestAppendOnly          o *trigger* morde: nem `UPDATE` nem `DELETE`
    TestGuardaDeArranque    o `confirmar()` que da o codigo de saida 7
    TestEscreverAserio      uma linha por chamada, com os catorze valores
    TestPrivacidade         a linha nao leva *prompt*, resposta nem telefone
    TestIsolamento          X-04, com canarios
    TestRestricoes          os `CHECK` da revisao `0023`, um a um
    TestAParticao           a `DEFAULT` existe e tem RLS; uma nova nasce sem *trigger*

O que **so** aqui se prova, e nao se prova com uma base falsa:

| Propriedade | Porque precisa da base |
|---|---|
| *append-only* | o `REVOKE` sozinho nao prende o dono e o *trigger* normal nao prende quem pode `session_replication_role`. Sao tres camadas, cada uma contra o servidor |
| o `INSERT` por coluna | o `GRANT` e por coluna; uma coluna a mais no `INSERT` do codigo da `42501`, e num duplo nao se ve |
| a RLS | a politica e da base. O `WITH CHECK` e o que impede uma linha de custo no nome de outro tenant — o unico tipo de escrita que esta tabela aceita |
| os `CHECK` | um `resultado` fora do dominio, um custo negativo, ou uma recusa de destino com custo preenchido sao recusados pelo servidor |
| a particao | para o *gate* 6, uma particao e uma tabela; que ela tenha `FORCE` so se ve no catalogo |
| o varrimento de privacidade | **e sobre os dados**, nao sobre o DDL. E a licao do KAM-026: o varrimento dele dava zero por procurar texto num campo `msgpack` |
"""

from __future__ import annotations

import unittest
import uuid
from decimal import Decimal

from tests import factories
from tests_agr.base import ComAgr

from kamba_agr.llm import registo  # noqa: E402

TABELA = "dat.llm_call_log"
PARTICAO = "dat.llm_call_log_default"

#: O que uma linha valida leva, para os ensaios variarem um campo de cada vez.
def _linha(tenant_id: str, **trocas) -> registo.LinhaDeChamada:
    campos = {
        "tenant_id": tenant_id,
        "trace_id": "0af7651916cd43dd8448eb211c80319c",
        "papel": "chat",
        "modelo": "por_decidir",
        "fornecedor": "anthropic",
        "resultado": "ok",
        "vertical": "vendedor",
        "no_grafo": "compose",
        "graph_version": "1.0.0",
        "tokens_in": 3000,
        "tokens_out": 300,
        "tokens_cache": 0,
        "custo_usd": Decimal("0.00045"),
        "latencia_ms": 250,
    }
    campos.update(trocas)
    return registo.LinhaDeChamada(**campos)


class _ComLlm(ComAgr):
    def setUp(self) -> None:
        super().setUp()
        # O tenant semeia-se pela `factories.tenant` com o cursor `semente` do
        # `ComAgr` (`autocommit`), e registra-se em `_tenants` para a limpeza
        # dele o apagar — e a mesma via do `criar_conversa`.
        self.tenant = factories.tenant(self.semente)
        self._tenants.append(self.tenant)
        self.ligacao_app = self.ligar("app")
        # **Por `addCleanup`, e sem abrir ligacao nenhuma.** Os `addCleanup`
        # correm em LIFO depois do `tearDown`, pelo que este — registado depois
        # do `_limpar` do `ComAgr` — corre **antes** dele: as linhas de custo
        # saem antes dos *tenants* que elas referenciam.
        #
        # E usa o cursor `semente` que o `ComAgr` ja tem (admin, `autocommit`).
        # A primeira versao fechava a `ligacao_app` num `addCleanup` **e** abria
        # uma ligacao nova na limpeza; a `ComBase.tearDown` fecha todas as que
        # sairam de `ligar()`, pelo que as duas coisas davam
        # `InterfaceError: connection is closed` em 41 baterias — nenhuma pela
        # razao que mediam.
        self.addCleanup(self._limpar_llm)

    def _limpar_llm(self) -> None:
        """A tabela e *append-only*: o `DELETE` e recusado ao `kamba_app` e ao dono.

        Limpa-se como `admin`, com o *trigger* desligado — a mesma escolha que o
        `test_tool_audit.py` faz, pela mesma razao.
        """
        self.semente.execute(
            f"ALTER TABLE {PARTICAO} DISABLE TRIGGER "
            "llm_call_log_sem_update_nem_delete"
        )
        self.semente.execute(f"DELETE FROM {PARTICAO}")
        self.semente.execute(
            f"ALTER TABLE {PARTICAO} ENABLE ALWAYS TRIGGER "
            "llm_call_log_sem_update_nem_delete"
        )

    def contar(self) -> int:
        return self.consultar(f"SELECT count(*) FROM {TABELA}")[0][0]

    def escrever(self, linha: registo.LinhaDeChamada) -> bool:
        return registo.escrever(self.ligacao_app, linha)


class TestOEsquemaEAsColunas(_ComLlm):
    def test_o_esquema_dat_existe(self) -> None:
        linhas = self.consultar(
            "SELECT nspname FROM pg_namespace WHERE nspname = 'dat'"
        )
        self.assertEqual(linhas, [("dat",)])

    def test_as_dezesseis_colunas(self) -> None:
        linhas = self.consultar(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'dat' AND table_name = 'llm_call_log' "
            "ORDER BY ordinal_position"
        )
        nomes = [n for (n,) in linhas]
        # **Dezesseis e nao catorze**: o DDL do `docs/tecnica/06` §14 tem
        # catorze, e esta tabela acrescenta o `papel` e o `graph_version` — sem
        # os quais o «custo por papel» do DoD nao e calculavel de lado nenhum.
        self.assertEqual(len(nomes), 16, nomes)
        self.assertEqual(nomes[:3], ["id", "ts", "tenant_id"])
        # As duas que o `docs/tecnica/06` §14 nao tem, e sem as quais o custo
        # por papel do DoD nao e calculavel.
        self.assertIn("papel", nomes)
        self.assertIn("graph_version", nomes)

    def test_as_colunas_do_chamador_sao_as_do_codigo(self) -> None:
        """Se divergirem, o `INSERT` rebenta por privilegio — mas em producao."""
        self.assertEqual(len(registo.COLUNAS), 14)
        self.assertNotIn("id", registo.COLUNAS)
        self.assertNotIn("ts", registo.COLUNAS)

    def test_e_particionada_por_ts(self) -> None:
        linhas = self.consultar(
            "SELECT partstrat FROM pg_partitioned_table p "
            "JOIN pg_class c ON c.oid = p.partrelid "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'dat' AND c.relname = 'llm_call_log'"
        )
        self.assertEqual(linhas, [("r",)], "RANGE, como o §14 manda")

    def test_o_custo_e_numeric_e_nao_virgula_flutuante(self) -> None:
        linhas = self.consultar(
            "SELECT data_type, numeric_precision, numeric_scale "
            "FROM information_schema.columns WHERE table_schema = 'dat' "
            "AND table_name = 'llm_call_log' AND column_name = 'custo_usd'"
        )
        self.assertEqual(linhas, [("numeric", 12, 6)])


class TestAppendOnly(_ComLlm):
    """Uma linha de custo que se pudesse alterar nao era um registo de custo."""

    def test_o_app_nao_tem_update_nem_delete(self) -> None:
        self.escrever(_linha(self.tenant))
        for privilegio in ("UPDATE", "DELETE"):
            with self.subTest(privilegio=privilegio):
                linhas = self.consultar(
                    f"SELECT has_table_privilege('kamba_app', '{TABELA}', '{privilegio}')"
                )
                self.assertEqual(linhas, [(False,)])

    def test_o_trigger_recusa_update_ao_dono(self) -> None:
        """O `REVOKE` nao prende o dono; o `ENABLE ALWAYS` prende."""
        self.escrever(_linha(self.tenant))
        with self.assertRaises(Exception) as apanhado:
            self.semente.execute(f"UPDATE {PARTICAO} SET custo_usd = 0")
        self.assertIn("append-only", str(apanhado.exception))

    def test_o_trigger_recusa_delete_ao_dono(self) -> None:
        self.escrever(_linha(self.tenant))
        with self.assertRaises(Exception) as apanhado:
            self.semente.execute(f"DELETE FROM {PARTICAO}")
        self.assertIn("append-only", str(apanhado.exception))

    def test_o_trigger_esta_ENABLE_ALWAYS(self) -> None:
        """Um *trigger* normal nao prende quem pode `session_replication_role`."""
        linhas = self.consultar(
            "SELECT tgenabled FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'dat' AND c.relname = 'llm_call_log_default' "
            "AND t.tgname = 'llm_call_log_sem_update_nem_delete'"
        )
        self.assertEqual(linhas, [("A",)], "'A' = ALWAYS")


class TestGuardaDeArranque(_ComLlm):
    """O `confirmar()` que da o codigo de saida 7."""

    def test_o_app_passa(self) -> None:
        registo.confirmar(self.ligar("app"))

    def test_um_papel_sem_insert_levanta(self) -> None:
        with self.assertRaises(registo.RegistoIndisponivelError):
            registo.confirmar(self.ligar("resolver"))

    def test_o_agr_nao_tem_nada_no_dat(self) -> None:
        """O papel do checkpointer nao chega ao custo de ninguem (KAM-026)."""
        with self.assertRaises(registo.RegistoIndisponivelError):
            registo.confirmar(self.ligar("agr"))

    def test_o_confirmar_nao_escreve_nada(self) -> None:
        antes = self.contar()
        registo.confirmar(self.ligar("app"))
        self.assertEqual(self.contar(), antes)


class TestEscreverAserio(_ComLlm):
    def test_uma_linha_com_os_catorze_valores(self) -> None:
        self.assertTrue(self.escrever(_linha(self.tenant)))
        linhas = self.consultar(
            "SELECT tenant_id::text, trace_id, vertical, no_grafo, papel, "
            "graph_version, modelo, fornecedor, tokens_in, tokens_out, "
            "tokens_cache, custo_usd, latencia_ms, resultado "
            f"FROM {TABELA}"
        )
        self.assertEqual(len(linhas), 1)
        linha = linhas[0]
        self.assertEqual(linha[0], self.tenant)
        self.assertEqual(linha[4], "chat")
        self.assertEqual(linha[11], Decimal("0.000450"), "o numero do criterio 5")
        self.assertEqual(linha[13], "ok")

    def test_o_ts_e_o_id_nao_sao_do_chamador(self) -> None:
        self.escrever(_linha(self.tenant))
        linhas = self.consultar(f"SELECT id, ts IS NOT NULL FROM {TABELA}")
        self.assertEqual(len(linhas), 1)
        self.assertGreaterEqual(linhas[0][0], 1)
        self.assertTrue(linhas[0][1])

    def test_uma_recusa_de_destino_escreve_linha(self) -> None:
        """Criterio 5: uma chamada recusada e uma chamada."""
        self.assertTrue(
            self.escrever(
                _linha(
                    self.tenant,
                    resultado="destino_negado",
                    tokens_in=None, tokens_out=None, tokens_cache=None, custo_usd=None,
                )
            )
        )
        linhas = self.consultar(f"SELECT resultado FROM {TABELA}")
        self.assertEqual(linhas, [("destino_negado",)])


class TestPrivacidade(_ComLlm):
    """Criterio 5 e DoD: a linha **sem conteudo**. Por varrimento, com canarios."""

    CANARIOS = (
        "SAPATOS-VERMELHOS-CANARIO-42",
        "RESPOSTA-DO-MODELO-CANARIO-99",
        "+244923456789",
        "923456789",
    )

    def test_nenhum_canario_cabe_na_tabela(self) -> None:
        """Nao e um teste de intencao: escreve-se o canario em cada coluna de
        texto que o chamador controla, e confirma-se que **nao ha** coluna onde
        ele entre com significado.

        Com `trace_id`, `no_grafo` e `modelo` a aceitarem texto livre, a
        pergunta honesta nao e «a tabela recusa isto?» — recusa nada — mas «o
        **codigo** poe lá conteudo?». Por isso o varrimento corre sobre as
        linhas que o `kamba_agr.llm.cliente` escreve, e esta bateria confirma o
        que o DDL garante: nao existe coluna de *prompt*, de resposta nem de
        telefone.
        """
        colunas = [
            n for (n,) in self.consultar(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'dat' AND table_name = 'llm_call_log'"
            )
        ]
        for proibida in ("prompt", "mensagem", "conteudo", "texto", "resposta",
                         "telefone", "msisdn", "corpo", "body", "content"):
            with self.subTest(coluna=proibida):
                self.assertNotIn(proibida, colunas)

    def test_o_varrimento_dos_dados_nao_encontra_canario(self) -> None:
        """O varrimento a serio: escreve-se uma linha e procura-se nos dados.

        **O canario do canario:** escreve-se tambem uma linha **com** o canario
        num campo de texto, de proposito, para provar que o varrimento o
        **encontraria** se lá estivesse. Sem isto, um varrimento que procurasse
        no sitio errado dava zero e o criterio passava pela razao errada — que e
        exactamente o que aconteceu no KAM-026.
        """
        self.escrever(_linha(self.tenant))
        self.assertEqual(self._varrer(), [], "a linha normal nao leva canario")

        self.escrever(_linha(self.tenant, no_grafo=self.CANARIOS[0]))
        encontrados = self._varrer()
        self.assertTrue(
            encontrados,
            "o varrimento tem de **encontrar** um canario plantado, senao nao "
            "prova nada sobre a sua ausencia",
        )

    def _varrer(self) -> list[tuple]:
        condicoes = " OR ".join(
            "(trace_id LIKE %s OR coalesce(vertical,'') LIKE %s "
            "OR coalesce(no_grafo,'') LIKE %s OR modelo LIKE %s "
            "OR fornecedor LIKE %s OR coalesce(graph_version,'') LIKE %s)"
            for _ in self.CANARIOS
        )
        parametros: list[str] = []
        for canario in self.CANARIOS:
            parametros.extend([f"%{canario}%"] * 6)
        return self.consultar(
            f"SELECT id FROM {TABELA} WHERE {condicoes}", tuple(parametros)
        )


class TestIsolamento(_ComLlm):
    """X-04: o tenant A nao le nem escreve o custo do tenant B."""

    def setUp(self) -> None:
        super().setUp()
        self.outro = factories.tenant(self.semente)
        self._tenants.append(self.outro)

    def test_nao_se_escreve_no_nome_de_outro_tenant(self) -> None:
        """O `WITH CHECK` da politica. E o unico tipo de escrita que a tabela aceita."""
        from kamba_core import tenant_guard

        with self.assertRaises(Exception):
            with tenant_guard.tx(self.ligacao_app, self.tenant) as cursor:
                cursor.execute(
                    registo.SQL_ESCREVER, _linha(self.outro).parametros()
                )
        self.ligacao_app.rollback()

    def test_sem_contexto_nao_se_escreve(self) -> None:
        cursor = self.ligar("app").cursor()
        with self.assertRaises(Exception):
            cursor.execute(registo.SQL_ESCREVER, _linha(self.tenant).parametros())

    def test_o_app_nao_le_a_tabela(self) -> None:
        """Quem produz o registo nao e quem o audita (razao da `0021`)."""
        linhas = self.consultar(
            f"SELECT has_table_privilege('kamba_app', '{TABELA}', 'SELECT')"
        )
        self.assertEqual(linhas, [(False,)])

    def test_quem_le_e_o_audit_e_o_batch(self) -> None:
        for papel in ("kamba_audit", "kamba_batch"):
            with self.subTest(papel=papel):
                linhas = self.consultar(
                    f"SELECT has_table_privilege('{papel}', '{TABELA}', 'SELECT')"
                )
                self.assertEqual(linhas, [(True,)])

    def test_o_batch_nao_apaga(self) -> None:
        """A retencao e `DROP` de particao, nao `DELETE` (razao da `0019`)."""
        linhas = self.consultar(
            f"SELECT has_table_privilege('kamba_batch', '{TABELA}', 'DELETE')"
        )
        self.assertEqual(linhas, [(False,)])


class TestRestricoes(_ComLlm):
    """Os `CHECK` da revisao `0023`, um a um, contra o servidor."""

    def _recusa(self, **trocas) -> None:
        from kamba_core import tenant_guard

        with self.assertRaises(Exception):
            with tenant_guard.tx(self.ligacao_app, self.tenant) as cursor:
                cursor.execute(
                    registo.SQL_ESCREVER, _linha(self.tenant, **trocas).parametros()
                )
        self.ligacao_app.rollback()

    def test_um_resultado_fora_do_dominio(self) -> None:
        self._recusa(resultado="talvez")

    def test_os_seis_resultados_passam(self) -> None:
        from kamba_agr.llm.erros import RESULTADOS

        for resultado in RESULTADOS:
            with self.subTest(resultado=resultado):
                sem_consumo = resultado == "destino_negado"
                linha = _linha(
                    self.tenant,
                    resultado=resultado,
                    tokens_in=None if sem_consumo else 10,
                    tokens_out=None if sem_consumo else 1,
                    tokens_cache=None if sem_consumo else 0,
                    custo_usd=None if sem_consumo else Decimal("0.000001"),
                )
                self.assertTrue(self.escrever(linha), resultado)

    def test_um_papel_fora_da_lista_fechada(self) -> None:
        self._recusa(papel="encaminhador")

    def test_os_quatro_papeis_passam(self) -> None:
        from kamba_agr.llm.aliases import PAPEIS

        for papel in PAPEIS:
            with self.subTest(papel=papel):
                self.assertTrue(self.escrever(_linha(self.tenant, papel=papel)), papel)

    def test_tokens_negativos(self) -> None:
        self._recusa(tokens_in=-1)

    def test_custo_negativo(self) -> None:
        self._recusa(custo_usd=Decimal("-0.1"))

    def test_latencia_negativa(self) -> None:
        self._recusa(latencia_ms=-1)

    def test_um_destino_negado_com_custo(self) -> None:
        """Afirmava que se pagou por uma chamada que nunca saiu de Angola."""
        self._recusa(resultado="destino_negado", custo_usd=Decimal("0.00045"))

    def test_um_destino_negado_com_tokens(self) -> None:
        self._recusa(
            resultado="destino_negado", tokens_in=3000,
            tokens_out=None, tokens_cache=None, custo_usd=None,
        )


class TestAParticao(_ComLlm):
    def test_a_particao_por_omissao_existe(self) -> None:
        linhas = self.consultar(
            "SELECT c.relname FROM pg_class c JOIN pg_namespace n "
            "ON n.oid = c.relnamespace WHERE n.nspname = 'dat' "
            "AND c.relname = 'llm_call_log_default'"
        )
        self.assertEqual(linhas, [("llm_call_log_default",)])

    def test_o_pai_e_a_particao_tem_rls_force(self) -> None:
        """Para o *gate* 6 uma particao e uma tabela: sem isto, falhava."""
        linhas = self.consultar(
            "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity "
            "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'dat' ORDER BY c.relname"
        )
        por_nome = {n: (rls, force) for n, rls, force in linhas}
        for tabela in ("llm_call_log", "llm_call_log_default"):
            with self.subTest(tabela=tabela):
                self.assertEqual(por_nome.get(tabela), (True, True))

    def test_a_politica_chama_se_tenant_iso(self) -> None:
        linhas = self.consultar(
            "SELECT tablename, policyname FROM pg_policies "
            "WHERE schemaname = 'dat' ORDER BY tablename"
        )
        self.assertEqual(
            linhas,
            [("llm_call_log", "tenant_iso"), ("llm_call_log_default", "tenant_iso")],
        )

    def test_uma_particao_nova_nasce_sem_o_trigger(self) -> None:
        """A limitacao esta escrita na revisao; aqui **ve-se**.

        Sem esta bateria, quem criar particoes mensais (KAM-071) descobria a
        falta quando alguem alterasse uma linha de custo — e nao descobria.
        """
        self.addCleanup(self._largar_particao_de_ensaio)
        self.semente.execute(
            "CREATE TABLE dat.llm_call_log_ensaio PARTITION OF dat.llm_call_log "
            "FOR VALUES FROM ('2020-01-01') TO ('2020-02-01')"
        )
        linhas = self.consultar(
            "SELECT count(*) FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'dat' AND c.relname = 'llm_call_log_ensaio' "
            "AND NOT t.tgisinternal"
        )
        self.assertEqual(
            linhas, [(0,)],
            "uma particao nova nasce sem o trigger: e o que a revisao 0023 diz, "
            "e e o que o KAM-071 tem de por quando criar as mensais",
        )

    def _largar_particao_de_ensaio(self) -> None:
        self.semente.execute("DROP TABLE IF EXISTS dat.llm_call_log_ensaio")


if __name__ == "__main__":
    unittest.main()
