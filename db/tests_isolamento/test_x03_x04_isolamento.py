"""X-03 e X-04 — o isolamento, tentado contra dados reais de dois tenants.

Criterios de aceitacao 2, 3, 4 e 5 do KAM-004. Tudo parametrizado sobre as
tabelas que o **catalogo** descobre: uma tabela nova com `tenant_id` entra
sozinha em cada um destes testes.

A regra de todos eles: **o teste so vale se a metade positiva tambem se
verificar.** «A nao ve as linhas de B» prova-se trivialmente com uma base vazia
ou com uma politica que nao deixa ver nada; por isso cada caso afirma primeiro
que A ve as **suas**.
"""

from __future__ import annotations

import sys
import threading
import uuid
from pathlib import Path

import ligacao
from tests.base import PRIVILEGIO_INSUFICIENTE
from tests_isolamento import sementes
from tests_isolamento.base import ComDoisTenants, definir_contexto

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "libs" / "py-core" / "src"))

from kamba_core import tenant_guard  # noqa: E402

#: `invalid_text_representation`: o que o `::uuid` da politica devolve a um
#: contexto que nao e um UUID.
TEXTO_INVALIDO = "22P02"


def _linhas(cursor, sql: str, parametros: tuple = ()) -> list[tuple]:
    cursor.execute(sql, parametros)
    return [tuple(linha) for linha in cursor.fetchall()]


class TestX03LeituraCruzada(ComDoisTenants):
    """Com contexto A, `SELECT *` nao devolve nada de B."""

    def test_onde_o_papel_nao_le_o_select_nem_chega_a_politica(self) -> None:
        """A `events_dlq`: `kamba_app` escreve e **nao** le (KAM-006).

        Provar que a politica devolve zero linhas seria provar menos: aqui nao
        ha sequer privilegio, e e por isso que a leitura rebenta com `42501`
        antes de a politica ser consultada. Se alguem der `SELECT` a este papel,
        este teste fica vermelho — e e isso que se quer, porque o `id` da DLQ e
        sequencial e uma leitura mede o volume de falhas do vizinho.
        """
        sem_leitura = self.por_tabela_sem_leitura()
        self.assertTrue(sem_leitura, "a forma «escreve e nao le» deixou de existir")
        for schema, tabela, _coluna, receita in sem_leitura:
            with self.subTest(tabela=f"{schema}.{tabela}"):
                cursor = self.cursor_de(receita.papel, self.a.id)
                with self.assertRaises(Exception) as apanhado:
                    cursor.execute(f"SELECT * FROM {schema}.{tabela}")
                self.assertIn("42501", str(apanhado.exception))

    def test_a_ve_as_suas_linhas_e_nenhuma_de_b(self) -> None:
        for schema, tabela, coluna, receita in self.por_tabela():
            with self.subTest(tabela=f"{schema}.{tabela}"):
                cursor = self.cursor_de(receita.papel, self.a.id)
                linhas = _linhas(cursor, f"SELECT * FROM {schema}.{tabela}")
                self.assertTrue(linhas, "A nao ve as suas proprias linhas")

                texto = " ".join(str(celula) for linha in linhas for celula in linha)
                self.assertIn(str(self.a.guardado((schema, tabela))), texto)
                self.assertNotIn(str(self.b.guardado((schema, tabela))), texto)
                self.assertNotIn(self.b.id, texto)

                de_b = _linhas(
                    cursor,
                    f"SELECT count(*) FROM {schema}.{tabela} WHERE {coluna} = %s",
                    (self.b.id,),
                )
                self.assertEqual(de_b, [(0,)])

    def test_e_simetrico(self) -> None:
        """B tambem nao ve A: uma politica que so funcionasse num sentido passava acima."""
        for schema, tabela, _, receita in self.por_tabela():
            with self.subTest(tabela=f"{schema}.{tabela}"):
                cursor = self.cursor_de(receita.papel, self.b.id)
                texto = " ".join(
                    str(celula)
                    for linha in _linhas(cursor, f"SELECT * FROM {schema}.{tabela}")
                    for celula in linha
                )
                self.assertIn(str(self.b.guardado((schema, tabela))), texto)
                self.assertNotIn(str(self.a.guardado((schema, tabela))), texto)

    def test_procurar_o_canario_de_b_por_valor_nao_o_encontra(self) -> None:
        """Um `WHERE` que nomeia a linha de B nao a traz: a politica soma-se por E."""
        for schema, tabela, _, receita in self.por_tabela():
            with self.subTest(tabela=f"{schema}.{tabela}"):
                cursor = self.cursor_de(receita.papel, self.a.id)
                consulta = (
                    f"SELECT count(*) FROM {schema}.{tabela} "
                    f"WHERE {receita.coluna_do_canario} = %s"
                )
                # A metade positiva: a mesma consulta encontra o canario de A.
                self.assertEqual(
                    _linhas(cursor, consulta, (self.a.guardado((schema, tabela)),)),
                    [(1,)],
                )
                encontradas = _linhas(
                    cursor, consulta, (self.b.guardado((schema, tabela)),)
                )
                self.assertEqual(encontradas, [(0,)])

    def test_um_contexto_de_tenant_inexistente_nao_ve_ninguem(self) -> None:
        for schema, tabela, _, receita in self.por_tabela():
            with self.subTest(tabela=f"{schema}.{tabela}"):
                cursor = self.cursor_de(receita.papel, str(uuid.uuid4()))
                self.assertEqual(
                    _linhas(cursor, f"SELECT count(*) FROM {schema}.{tabela}"), [(0,)]
                )


class TestContactosVistosPelaAplicacao(ComDoisTenants):
    """`contacts` e a unica tabela de identidade que `kamba_app` le (seis colunas).

    A suite ataca cada tabela com o papel que a le por inteiro — `kamba_identity`
    nas de identidade —, e isso deixava de fora a leitura parcial da aplicacao:
    e ela que faz os *joins* de negocio por `contact_id`.
    """

    CONSULTA = (
        "SELECT contact_id::text, tenant_id::text, erased_at, merged_into "
        "FROM platform.contacts"
    )

    def test_a_ve_o_seu_contacto_e_nenhum_de_b(self) -> None:
        for meu, outro in ((self.a, self.b), (self.b, self.a)):
            with self.subTest(tenant=meu.id):
                linhas = _linhas(self.cursor_app(meu.id), self.CONSULTA)
                self.assertEqual([linha[1] for linha in linhas], [meu.id])
                de_outro = _linhas(
                    self.cursor_app(meu.id),
                    "SELECT count(*) FROM platform.contacts WHERE tenant_id = %s",
                    (outro.id,),
                )
                self.assertEqual(de_outro, [(0,)])

    def test_sem_contexto_ou_com_um_tenant_que_nao_existe_nao_ve_nenhum(self) -> None:
        self.assertEqual(_linhas(self.cursor_app(), self.CONSULTA), [])
        self.assertEqual(_linhas(self.cursor_app(str(uuid.uuid4())), self.CONSULTA), [])

    def test_pelo_contact_id_de_b_tambem_nao(self) -> None:
        """Saber o `contact_id` de outro tenant nao o torna visivel."""
        de_b = _linhas(
            self._cursores["admin"],
            "SELECT contact_id::text FROM platform.contacts WHERE tenant_id = %s",
            (self.b.id,),
        )[0][0]
        self.assertEqual(
            _linhas(
                self.cursor_app(self.a.id),
                "SELECT count(*) FROM platform.contacts WHERE contact_id = %s",
                (de_b,),
            ),
            [(0,)],
        )


class TestX04SemContexto(ComDoisTenants):
    """Sem `SET LOCAL`, zero linhas e nenhuma escrita. Falha fechada."""

    def test_sem_contexto_cada_tabela_devolve_zero_linhas(self) -> None:
        for schema, tabela, _, receita in self.por_tabela():
            with self.subTest(tabela=f"{schema}.{tabela}"):
                cursor = self.cursor_de(receita.papel)
                self.assertEqual(
                    _linhas(cursor, f"SELECT count(*) FROM {schema}.{tabela}"), [(0,)]
                )

    def test_com_o_contexto_vazio_tambem(self) -> None:
        """`''` e o que a variavel vale depois de um `SET LOCAL` expirar."""
        for schema, tabela, _, receita in self.por_tabela():
            with self.subTest(tabela=f"{schema}.{tabela}"):
                cursor = self.cursor_de(receita.papel)
                definir_contexto(cursor, None)
                self.assertEqual(
                    _linhas(cursor, f"SELECT count(*) FROM {schema}.{tabela}"), [(0,)]
                )

    def test_insert_sem_contexto_falha(self) -> None:
        """Todas as que o papel escreve — **inclusive as que ele nao le**.

        O `por_tabela()` tira as que o papel nao le, e usa-lo aqui tirava a
        `events_dlq` do `WITH CHECK`: a unica tabela em que `kamba_app`
        escreve as cegas ficava sem teste de escrita cruzada nenhum.
        """
        for schema, tabela, _, receita in self.por_tabela_que_escreve():
            with self.subTest(tabela=f"{schema}.{tabela}"):
                cursor = self.cursor_de(receita.papel)
                self._inserir_tem_de_falhar(cursor, receita, self.a.id)

    def test_onde_o_papel_nao_escreve_o_insert_nem_chega_a_politica(self) -> None:
        """`events_log` e arquivo: so o `kamba_batch` escreve, e ele e auditado.

        Nenhum papel sujeito a RLS lhe insere, pelo que nao ha `WITH CHECK` que
        se possa exercer. O que se prova e mais forte: o papel que a **le** nao
        tem sequer o privilegio de `INSERT`, e por isso a politica nunca e a
        unica coisa entre o produtor e o arquivo.
        """
        sem_escrita = self.por_tabela_sem_escrita()
        self.assertTrue(sem_escrita, "nenhuma tabela e so-leitura para o seu papel")
        for schema, tabela, _, receita in sem_escrita:
            with self.subTest(tabela=f"{schema}.{tabela}"):
                cursor = self.cursor_de(receita.papel, self.a.id)
                self._inserir_sem_privilegio(cursor, receita, self.a.id)

    def test_um_contexto_que_nao_e_uuid_e_erro_e_nao_linhas(self) -> None:
        """Falha fechada pelo lado ruidoso: o `::uuid` da politica rebenta."""
        for schema, tabela, _, receita in self.por_tabela():
            with self.subTest(tabela=f"{schema}.{tabela}"):
                cursor = self.cursor_de(receita.papel)
                definir_contexto(cursor, "nao-e-um-uuid")
                self.assertErroSql(
                    TEXTO_INVALIDO, cursor, f"SELECT count(*) FROM {schema}.{tabela}"
                )

    def test_o_dono_das_tabelas_tambem_nao_ve_nada(self) -> None:
        """`FORCE` vincula o dono. Sem ele, `kamba_migrator` via tudo."""
        cursor = self.ligar("migrator").cursor()
        for schema, tabela, _, _ in self.por_tabela():
            with self.subTest(tabela=f"{schema}.{tabela}"):
                self.assertEqual(
                    _linhas(cursor, f"SELECT count(*) FROM {schema}.{tabela}"), [(0,)]
                )


class TestEscritaCruzada(ComDoisTenants):
    """Com contexto A, nao se escreve em B."""

    def test_insert_com_o_tenant_de_b_sob_contexto_a_falha(self) -> None:
        """`WITH CHECK`. Para `tenants`, e criar um tenant cujo `id` nao e o do contexto.

        Itera o `por_tabela_que_escreve()`: uma tabela que o papel escreve sem
        ler precisa deste teste **mais** do que as outras, porque nela a
        politica e a unica coisa entre o produtor e a linha do vizinho.
        """
        for schema, tabela, _, receita in self.por_tabela_que_escreve():
            with self.subTest(tabela=f"{schema}.{tabela}"):
                cursor = self.cursor_de(receita.papel, self.a.id)
                alvo = str(uuid.uuid4()) if tabela == "tenants" else self.b.id
                self._inserir_tem_de_falhar(cursor, receita, alvo)

    def test_update_sobre_linhas_de_b_afecta_zero_linhas(self) -> None:
        for schema, tabela, coluna, receita in self.por_tabela():
            if receita.coluna_alteravel is None:
                continue  # ver `test_nas_tabelas_imutaveis_...`
            with self.subTest(tabela=f"{schema}.{tabela}"):
                cursor = self.cursor_de(receita.papel, self.a.id)
                cursor.execute(
                    f"UPDATE {schema}.{tabela} SET {receita.coluna_alteravel} = %s "
                    f"WHERE {coluna} = %s",
                    (receita.valor_alteravel, self.b.id),
                )
                self.assertEqual(cursor.rowcount, 0)

    def test_update_sem_where_so_toca_nas_linhas_de_a(self) -> None:
        """O caso perigoso: um `UPDATE` sem filtro. A politica e o filtro."""
        for schema, tabela, coluna, receita in self.por_tabela():
            if receita.coluna_alteravel is None:
                continue  # ver `test_nas_tabelas_imutaveis_...`
            with self.subTest(tabela=f"{schema}.{tabela}"):
                cursor = self.cursor_de(receita.papel, self.a.id)
                cursor.execute(
                    f"UPDATE {schema}.{tabela} SET {receita.coluna_alteravel} = "
                    f"{receita.coluna_alteravel}"
                )
                self.assertEqual(cursor.rowcount, 1)

    def test_nas_tabelas_imutaveis_o_papel_nao_tem_update(self) -> None:
        """Nao ha coluna alteravel porque nao ha `UPDATE` (KAM-005).

        O `events_outbox` e o `events_log` nao tem, para o papel que os le,
        nenhuma coluna que ele possa alterar: o estado de publicacao e do
        publicador e o arquivo e imutavel. Provar isso pela **ausencia de
        privilegio** e mais forte do que por politica — nao depende de a
        politica estar certa — e e por isso que os dois testes acima saltam
        estas tabelas em vez de inventarem uma coluna alteravel.
        """
        cobertas = 0
        for schema, tabela, _, receita in self.por_tabela():
            if receita.coluna_alteravel is not None:
                continue
            cobertas += 1
            with self.subTest(tabela=f"{schema}.{tabela}"):
                cursor = self.cursor_de(receita.papel, self.a.id)
                self.assertErroSql(
                    PRIVILEGIO_INSUFICIENTE,
                    cursor,
                    f"UPDATE {schema}.{tabela} SET {receita.coluna_do_canario} = "
                    f"{receita.coluna_do_canario}",
                )
        self.assertTrue(cobertas, "nenhuma tabela e imutavel para o seu papel")

    def test_update_nao_muda_uma_linha_de_a_para_b(self) -> None:
        """`WITH CHECK` tambem no `UPDATE`: A nao oferece uma linha sua a B.

        `kamba_app` nem tem `UPDATE` na coluna de tenant (KAM-003), pelo que o
        privilegio recusa antes da politica; prova-se a politica com o dono das
        tabelas, que tem todos os privilegios e esta sujeito a ela pelo `FORCE`.
        """
        cursor = self.ligar("migrator").cursor()
        definir_contexto(cursor, self.a.id)
        for schema, tabela, coluna, _ in self.por_tabela():
            if tabela == "tenants":
                continue  # a chave e a propria identidade: muda-la e outro teste
            if tabela == "tenant_usage":
                # KAM-009, revisao adversarial: o contador ganhou um trigger
                # `BEFORE UPDATE` (`tenant_usage_so_sobe`) que recusa mudar a
                # chave de uma linha, e ele dispara **antes** da politica.
                # A propriedade continua provada, por uma regra mais
                # apertada: a politica recusava mover a linha para B, o
                # trigger recusa move-la para onde quer que seja. Quem o
                # prova e `tests_ten/test_escalada.py`,
                # `test_a_linha_nao_muda_de_conta`; aqui so se regista que o
                # `42501` deixou de ser alcancavel nesta tabela.
                continue
            with self.subTest(tabela=f"{schema}.{tabela}"):
                self.assertErroSql(
                    PRIVILEGIO_INSUFICIENTE,
                    cursor,
                    f"UPDATE {schema}.{tabela} SET {coluna} = %s",
                    (self.b.id,),
                )

    def test_delete_sobre_linhas_de_b_afecta_zero_linhas(self) -> None:
        """`kamba_app` nao tem `DELETE` de todo; prova-se a politica com o dono."""
        cursor = self.ligar("migrator").cursor()
        definir_contexto(cursor, self.a.id)
        for schema, tabela, coluna, _ in reversed(self.por_tabela()):
            with self.subTest(tabela=f"{schema}.{tabela}"):
                cursor.execute(
                    f"DELETE FROM {schema}.{tabela} WHERE {coluna} = %s", (self.b.id,)
                )
                self.assertEqual(cursor.rowcount, 0)

    def test_o_unico_delete_fora_do_dono_tambem_nao_chega_a_b(self) -> None:
        """`kamba_identity` tem `DELETE` em `contact_endpoints` (apagamento do titular).

        E o unico papel de servico com `DELETE`, e por isso o unico em que a
        politica — e nao a falta de privilegio — e o que protege B.
        """
        cursor = self.cursor_de("identity", self.a.id)
        cursor.execute(
            "DELETE FROM platform.contact_endpoints WHERE tenant_id = %s", (self.b.id,)
        )
        self.assertEqual(cursor.rowcount, 0)
        cursor.execute("SAVEPOINT antes_de_apagar_tudo")
        cursor.execute("DELETE FROM platform.contact_endpoints")
        self.assertEqual(cursor.rowcount, 1, "um DELETE sem filtro so toca nas linhas de A")
        cursor.execute("ROLLBACK TO SAVEPOINT antes_de_apagar_tudo")
        sobram = _linhas(
            self._cursores["admin"],
            "SELECT count(*) FROM platform.contact_endpoints WHERE tenant_id = %s",
            (self.b.id,),
        )
        self.assertEqual(sobram, [(1,)])

    def test_como_kamba_app_o_delete_nem_chega_a_politica(self) -> None:
        cursor = self.cursor_app(self.a.id)
        for schema, tabela, _, _ in self.por_tabela():
            with self.subTest(tabela=f"{schema}.{tabela}"):
                self.assertErroSql(
                    PRIVILEGIO_INSUFICIENTE, cursor, f"DELETE FROM {schema}.{tabela}"
                )


class TestReutilizacaoDeLigacao(ComDoisTenants):
    """O contexto nao vaza entre transaccoes na mesma ligacao (criterio 5).

    E o cenario do *pool* em modo transaccao: a ligacao que serviu um pedido de
    A serve a seguir um pedido sem contexto, ou de B.
    """

    def contar(self, cursor, papel: str = "app") -> dict[str, int]:
        """Linhas visiveis em cada tabela que `papel` le. Nunca vazio."""
        contagens = {
            tabela: _linhas(cursor, f"SELECT count(*) FROM {schema}.{tabela}")[0][0]
            for schema, tabela, _, receita in self.por_tabela()
            if receita.papel == papel
        }
        self.assertTrue(contagens, f"nenhuma tabela e lida por {papel}")
        return contagens

    def test_ha_tabelas_para_os_dois_papeis(self) -> None:
        """Se um papel deixasse de ter tabelas, os testes abaixo passavam sem medir."""
        self.assertEqual(sementes.PAPEIS, ("app", "identity"))

    def test_depois_do_commit_a_transaccao_seguinte_nao_tem_contexto(self) -> None:
        for papel in sementes.PAPEIS:
            with self.subTest(papel=papel):
                conexao = self.ligar(papel)
                cursor = conexao.cursor()
                definir_contexto(cursor, self.a.id)
                self.assertTrue(all(n == 1 for n in self.contar(cursor, papel).values()))
                conexao.commit()

                self.assertTrue(all(n == 0 for n in self.contar(cursor, papel).values()))

    def test_depois_do_rollback_tambem(self) -> None:
        for papel in sementes.PAPEIS:
            with self.subTest(papel=papel):
                conexao = self.ligar(papel)
                cursor = conexao.cursor()
                definir_contexto(cursor, self.a.id)
                self.assertTrue(all(n == 1 for n in self.contar(cursor, papel).values()))
                conexao.rollback()

                self.assertTrue(all(n == 0 for n in self.contar(cursor, papel).values()))

    def test_a_ligacao_que_serviu_a_serve_b_sem_restos_de_a(self) -> None:
        for papel in sementes.PAPEIS:
            conexao = self.ligar(papel)
            cursor = conexao.cursor()
            definir_contexto(cursor, self.a.id)
            conexao.commit()

            definir_contexto(cursor, self.b.id)
            for schema, tabela, _, receita in self.por_tabela():
                if receita.papel != papel:
                    continue
                with self.subTest(tabela=f"{schema}.{tabela}"):
                    valores = _linhas(
                        cursor,
                        f"SELECT {receita.coluna_do_canario} FROM {schema}.{tabela}",
                    )
                    self.assertEqual(valores, [(self.b.guardado((schema, tabela)),)])

    def test_o_helper_tx_isola_e_nao_deixa_contexto(self) -> None:
        """O `tenant_guard.tx` real, contra a base: e ele que os servicos usam."""
        conexao = self.ligar("app")
        with tenant_guard.tx(conexao, self.a.id) as cursor:
            self.assertTrue(all(n == 1 for n in self.contar(cursor).values()))
            texto = str(_linhas(cursor, "SELECT * FROM platform.tenant_channels"))
            self.assertNotIn(self.b.id, texto)

        cursor = conexao.cursor()
        self.assertTrue(all(n == 0 for n in self.contar(cursor).values()))

    def test_o_helper_tx_isola_tambem_o_papel_de_identidade(self) -> None:
        """O mesmo *helper*, com `kamba_identity`: e com ele que o cofre se le."""
        conexao = self.ligar("identity")
        with tenant_guard.tx(conexao, self.a.id) as cursor:
            self.assertTrue(all(n == 1 for n in self.contar(cursor, "identity").values()))
            texto = str(_linhas(cursor, "SELECT * FROM platform.contact_endpoints"))
            self.assertNotIn(self.b.id, texto)
            self.assertIn(self.a.id, texto)

        cursor = conexao.cursor()
        self.assertTrue(all(n == 0 for n in self.contar(cursor, "identity").values()))

    def test_o_helper_tx_batch_ve_os_dois_tenants(self) -> None:
        conexao = self.ligar("batch")
        with tenant_guard.tx_batch(conexao, "ensaio_de_isolamento") as cursor:
            vistos = {
                linha[0]
                for linha in _linhas(
                    cursor,
                    "SELECT id::text FROM platform.tenants WHERE id IN (%s, %s)",
                    (self.a.id, self.b.id),
                )
            }
        self.assertEqual(vistos, {self.a.id, self.b.id})

    def test_o_helper_tx_batch_com_kamba_app_nao_contorna_nada(self) -> None:
        """Dar um nome de job a uma ligacao de `kamba_app` nao lhe da `BYPASSRLS`."""
        with tenant_guard.tx_batch(self.ligar("app"), "ensaio_de_isolamento") as cursor:
            self.assertTrue(all(n == 0 for n in self.contar(cursor).values()))


class TestConcorrencia(ComDoisTenants):
    """50 transaccoes paralelas a alternar A e B nao vazam contexto.

    Cinco ligacoes, dez transaccoes cada, a alternar de tenant **na mesma
    ligacao** — que e onde um contexto de sessao vazaria. Cada transaccao
    afirma que ve o seu canario e nao o do outro.
    """

    LIGACOES = 5
    TRANSACCOES_POR_LIGACAO = 10

    def test_cinquenta_transaccoes_alternadas(self) -> None:
        erros: list[str] = []
        feitas: list[int] = []
        trinco = threading.Lock()
        barreira = threading.Barrier(self.LIGACOES)
        chave = ("platform", "tenant_channels")

        def trabalhar(indice: int) -> None:
            conexao = ligacao.ligar("app")
            try:
                barreira.wait(timeout=30)
                for volta in range(self.TRANSACCOES_POR_LIGACAO):
                    meu, outro = (
                        (self.a, self.b) if (indice + volta) % 2 == 0 else (self.b, self.a)
                    )
                    with tenant_guard.tx(conexao, meu.id) as cursor:
                        cursor.execute("SELECT waba_id FROM platform.tenant_channels")
                        vistos = [linha[0] for linha in cursor.fetchall()]
                    with trinco:
                        feitas.append(1)
                        if vistos != [meu.canarios[chave]]:
                            erros.append(
                                f"ligacao {indice}, volta {volta}: viu {len(vistos)} "
                                f"linha(s); a do outro tenant presente: "
                                f"{outro.canarios[chave] in vistos}"
                            )
            except Exception as erro:  # noqa: BLE001 — qualquer falha conta
                with trinco:
                    erros.append(f"ligacao {indice}: {type(erro).__name__}")
            finally:
                conexao.close()

        fios = [
            threading.Thread(target=trabalhar, args=(i,)) for i in range(self.LIGACOES)
        ]
        for fio in fios:
            fio.start()
        for fio in fios:
            fio.join(timeout=120)

        self.assertEqual(erros, [])
        self.assertEqual(sum(feitas), self.LIGACOES * self.TRANSACCOES_POR_LIGACAO)
        self.assertEqual(sum(feitas), 50)
