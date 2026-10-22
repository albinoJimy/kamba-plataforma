"""A revisao 0018 contra a base: o estado de coexistencia de um canal (KAM-017).

Cinco coisas, e quatro delas sao criterios do bloco pela letra:

1. **O «2.a execucao = no-op» do criterio 3 e do PostgreSQL.** O
   `SQL_MARCAR_PASSO` filtra por `NOT ($3 = ANY (passos_feitos))`, e a segunda
   passagem devolve **zero linhas**. Afirma-se contra um servidor a serio, com
   as duas ordens: o mesmo passo duas vezes, e os dois passos por ordem.

2. **A unicidade `(tenant_id, channel_id)` e o criterio 9.** «A reconexao
   reutiliza o ES de KAM-016 **sem criar canal duplicado**»: uma segunda
   abertura **repoe** a linha que la esta em vez de criar outra, e e o
   `ON CONFLICT ... DO UPDATE` que o faz. Afirma-se que a contagem fica em um e
   que os `passos_feitos` da ligacao anterior **nao** sobrevivem — sem isso, a
   sincronizacao nova nascia concluida sem ter corrido, que e precisamente o
   modo de falhar que o prazo de 24 h existe para apanhar.

3. **O dominio dos quatro estados e o dos seis motivos.** Os dois sao
   `CHECK` fechados, e confrontam-se com o `pg_get_constraintdef` **nos dois
   sentidos**: o que a revisao impoe e o que o contrato de TypeScript declara
   tem de ser o mesmo conjunto. E a licao que a `0008` e a `0009` pagaram por
   os deixar divergir.

4. **O `channel_coexistence_desligamento_ck` e uma igualdade e nao uma
   implicacao.** Um desligamento tem as duas metades ou nenhuma: so com o
   motivo, nao se sabe quando; so com o instante, nao se sabe porque. Ha um
   teste para cada metade.

5. **O `downgrade`** — «Migracoes reversiveis: `downgrade` testado». Desce com
   linhas e **nao recusa**, e a razao esta na propria revisao: o que se perde e
   o estado de uma **sincronizacao**, que nao e dinheiro (a `0010`) nem prova
   juridica (a `0015`) — e uma sincronizacao perdida refaz-se, que e o que o
   prazo das 24 h ja manda fazer quando cai.

A classe do `downgrade` nao herda de `ComBase`: controla ela propria a revisao
da base, e `ComBase` assume `head`.
"""

from __future__ import annotations

import unittest
import uuid

import ligacao
from tests import factories
from tests.base import (
    PRIVILEGIO_INSUFICIENTE,
    TABELAS,
    TABELAS_ATE_0017,
    VIOLACAO_DE_CHECK,
    VIOLACAO_DE_FK,
    VIOLACAO_DE_UNICIDADE,
    ComBase,
    alembic_ok,
    em_head,
    sqlstate,
)

#: Os quatro estados, como a revisao os declara e como o dicionario §3.22 os
#: fixa (emenda 1.31). O `sincronizado_sem_historico` e **terminal e
#: bem-sucedido**: e o criterio 4 inteiro.
ESTADOS = (
    "a_sincronizar",
    "sincronizado",
    "sincronizado_sem_historico",
    "falhado",
)

#: Cinco valores que o `CHECK` tem de recusar. O primeiro e um estado de
#: `tenant_channels` (os dois dominios usam a mesma palavra e nao sao o mesmo
#: dominio — e a razao de o dicionario o qualificar pela tabela); o segundo e o
#: terceiro sao plausiveis e nao existem; o quarto sao maiusculas; o quinto e a
#: cadeia vazia.
ESTADOS_RECUSADOS = ("ativo", "a_correr", "sem_historico", "SINCRONIZADO", "")

#: Os seis motivos de `PARTNER_REMOVED`, em minusculas (`E1` §2, CONFIRMADO).
MOTIVOS = (
    "primary_inactivity",
    "companion_inactivity",
    "business_downgrade",
    "change_number",
    "user_re_registered",
    "account_disconnected",
)

#: Quatro que o `CHECK` recusa. **O primeiro e a forma da Meta**, e e o caso que
#: importa: se as MAIUSCULAS entrassem, a traducao na fronteira deixava de ser
#: obrigatoria — e e ela que impede um `PRIMARY_INACTIVITY` de chegar ao
#: `outcome` de uma linha de registo, onde a gramatica o recusa e, em modo
#: estrito, o `Logger` **levanta**.
MOTIVOS_RECUSADOS = ("PRIMARY_INACTIVITY", "inactividade", "partner_removed", "")

#: Os dois passos que o `E1` §2 nomeia.
PASSOS = ("contactos", "historico")


def _tabelas(cursor) -> tuple[str, ...]:
    cursor.execute(
        "SELECT tablename::text FROM pg_tables WHERE schemaname = 'platform' ORDER BY 1"
    )
    return tuple(linha[0] for linha in cursor.fetchall())


def _definicao(cursor, restricao: str) -> str:
    cursor.execute(
        "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = %s",
        (restricao,),
    )
    linha = cursor.fetchone()
    return "" if linha is None else linha[0]


class TestCoexistenciaDoCanal(ComBase):
    """O que o DDL da `0018` promete.

    `ComBase` da uma ligacao que **nunca confirma**: cada teste desfaz o que
    escreveu, e e por isso que o tenant e o canal se semeiam em cada um.
    """

    def setUp(self) -> None:
        super().setUp()
        self.conexao = self.ligar("admin")
        self.cursor = self.conexao.cursor()
        self.tenant = factories.tenant(self.cursor)
        self.outro = factories.tenant(self.cursor)
        self.canal = factories.canal(self.cursor, self.tenant)
        self.canal_do_outro = factories.canal(self.cursor, self.outro)

    def _campos(self, **troca) -> dict:
        campos = {
            "tenant_id": self.tenant,
            "channel_id": self.canal,
            "prazo_em": "now() + interval '24 hours'",
        }
        campos.update(troca)
        return campos

    def _inserir(self, **troca):
        campos = self._campos(**troca)
        prazo = campos.pop("prazo_em")
        colunas = ", ".join([*campos, "prazo_em"])
        marcas = ", ".join(["%s"] * len(campos) + [prazo])
        self.cursor.execute(
            f"INSERT INTO platform.channel_coexistence ({colunas}) "
            f"VALUES ({marcas}) RETURNING id::text",
            tuple(campos.values()),
        )
        return self.cursor.fetchone()[0]

    def _recusa(self, sqlstate_esperado: str, restricao: str, **troca) -> None:
        """A insercao tem de falhar, com o SQLSTATE e a restricao esperados.

        Dentro de um `SAVEPOINT`, pela licao que o KAM-022 pagou e o KAM-016
        repetiu: um erro aborta a transaccao inteira no PostgreSQL, e sem o
        ponto de salvaguarda o **segundo** caso negativo de um `subTest` falhava
        com `25P02` em vez da violacao que se queria medir.

        A restricao confere-se **depois**, sobre a excepcao: o SQLSTATE sozinho
        nao distingue dois `23514` da mesma tabela, e um teste verde a medir
        outra restricao e pior do que nenhum.
        """
        import pg8000.dbapi

        campos = self._campos(**troca)
        prazo = campos.pop("prazo_em")
        colunas = ", ".join([*campos, "prazo_em"])
        marcas = ", ".join(["%s"] * len(campos) + [prazo])
        sql = (
            f"INSERT INTO platform.channel_coexistence ({colunas}) "
            f"VALUES ({marcas})"
        )
        self.cursor.execute("SAVEPOINT caso_negativo")
        try:
            with self.assertRaises(pg8000.dbapi.DatabaseError) as capturado:
                self.cursor.execute(sql, tuple(campos.values()))
        finally:
            self.cursor.execute("ROLLBACK TO SAVEPOINT caso_negativo")
        self.assertEqual(
            sqlstate(capturado.exception),
            sqlstate_esperado,
            f"falhou, mas nao pela razao esperada: {capturado.exception}",
        )
        self.assertIn(restricao, str(capturado.exception))

    # --------------------------------------------------------- a forma da linha

    def test_a_linha_nasce_a_sincronizar_sem_passos_e_com_contagens_a_zero(self) -> None:
        identificador = self._inserir()
        self.cursor.execute(
            "SELECT estado, passos_feitos, contactos_vistos, mensagens_vistas, "
            "       alertado_em, concluido_em, meta_error_code, ultimo_echo_em, "
            "       avisado_em, motivo_desligamento, desligado_em "
            "FROM platform.channel_coexistence WHERE id = %s",
            (identificador,),
        )
        linha = self.cursor.fetchone()
        self.assertEqual(linha[0], "a_sincronizar")
        self.assertEqual(linha[1], [])
        self.assertEqual(linha[2], 0)
        self.assertEqual(linha[3], 0)
        for valor in linha[4:]:
            self.assertIsNone(valor)

    def test_o_id_e_um_uuid_gerado(self) -> None:
        # O `kamba_app` **le e escreve** esta tabela, e com um `id` sequencial
        # esse papel media quantos canais a plataforma tem em coexistencia.
        primeiro = self._inserir()
        segundo = self._inserir(channel_id=factories.canal(self.cursor, self.tenant))
        self.assertNotEqual(primeiro, segundo)

    # ------------------------------- a unicidade por canal (criterio 9)

    def test_o_mesmo_canal_duas_vezes_e_recusado(self) -> None:
        self._inserir()
        self._recusa(VIOLACAO_DE_UNICIDADE, "channel_coexistence_canal_uq")

    def test_a_reposicao_nao_cria_segunda_linha_e_limpa_os_passos(self) -> None:
        """O criterio 9 pela base: a reconexao **repoe**, nao duplica.

        Este e o teste que vale a pena ler. O `SQL_ABRIR` e um
        `INSERT ... ON CONFLICT (tenant_id, channel_id) DO UPDATE`, e o que ele
        tem de garantir sao **duas** coisas e nao uma: que fica uma linha, e que
        a linha fica **limpa**. Deixar os `passos_feitos` da ligacao anterior
        fazia a sincronizacao nova nascer concluida sem ter corrido.
        """
        self._inserir()
        self.cursor.execute(
            "UPDATE platform.channel_coexistence "
            "SET passos_feitos = ARRAY['contactos','historico']::text[], "
            "    estado = 'sincronizado', concluido_em = now(), "
            "    contactos_vistos = 7, mensagens_vistas = 300 "
            "WHERE tenant_id = %s AND channel_id = %s",
            (self.tenant, self.canal),
        )
        self.cursor.execute(
            "INSERT INTO platform.channel_coexistence "
            "(tenant_id, channel_id, estado, iniciado_em, prazo_em) "
            "VALUES (%s, %s, 'a_sincronizar', now(), now() + interval '24 hours') "
            "ON CONFLICT (tenant_id, channel_id) DO UPDATE "
            "   SET estado = 'a_sincronizar', passos_feitos = '{}'::text[], "
            "       iniciado_em = EXCLUDED.iniciado_em, "
            "       prazo_em = EXCLUDED.prazo_em, alertado_em = NULL, "
            "       concluido_em = NULL, contactos_vistos = 0, "
            "       mensagens_vistas = 0, meta_error_code = NULL, "
            "       avisado_em = NULL, motivo_desligamento = NULL, "
            "       desligado_em = NULL, actualizado_at = now()",
            (self.tenant, self.canal),
        )
        self.cursor.execute(
            "SELECT count(*), max(estado), max(array_length(passos_feitos, 1)), "
            "       max(contactos_vistos), max(mensagens_vistas) "
            "FROM platform.channel_coexistence "
            "WHERE tenant_id = %s AND channel_id = %s",
            (self.tenant, self.canal),
        )
        quantas, estado, passos, contactos, mensagens = self.cursor.fetchone()
        self.assertEqual(quantas, 1)
        self.assertEqual(estado, "a_sincronizar")
        # `array_length` de um array vazio e `NULL`, nao `0`.
        self.assertIsNone(passos)
        self.assertEqual(contactos, 0)
        self.assertEqual(mensagens, 0)

    def test_o_mesmo_canal_noutro_tenant_entra(self) -> None:
        # A chave e composta com o `tenant_id`, pela razao da emenda 1.21.
        self._inserir()
        self._inserir(tenant_id=self.outro, channel_id=self.canal_do_outro)

    # ---------------------------------- o passo que so corre uma vez (criterio 3)

    def test_o_mesmo_passo_duas_vezes_marca_uma(self) -> None:
        """O «2.a execucao = no-op» do criterio 3, contra o servidor.

        **A asserção e o numero de linhas e nao o conteudo**: o critério diz
        «2.ª execução = *no-op*», e o que prova que foi *no-op* e o `UPDATE`
        nao ter encontrado linha — nao o array ter ficado igual, que tambem
        ficaria se o `||` corresse e o `CHECK` recusasse.
        """
        self._inserir()
        instrucao = (
            "UPDATE platform.channel_coexistence "
            "SET passos_feitos = passos_feitos || %s::text, "
            "    contactos_vistos = contactos_vistos + %s::integer, "
            "    mensagens_vistas = mensagens_vistas + %s::integer, "
            "    actualizado_at = now() "
            "WHERE tenant_id = %s AND channel_id = %s AND estado = 'a_sincronizar' "
            "  AND NOT (%s::text = ANY (passos_feitos)) "
            "RETURNING passos_feitos"
        )
        self.cursor.execute(
            instrucao, ("historico", 3, 120, self.tenant, self.canal, "historico")
        )
        self.assertEqual(len(self.cursor.fetchall()), 1)
        self.cursor.execute(
            instrucao, ("historico", 3, 120, self.tenant, self.canal, "historico")
        )
        self.assertEqual(len(self.cursor.fetchall()), 0)
        # E as contagens **nao** somaram duas vezes: e a mesma instrucao que
        # marca o passo e soma, de proposito — separa-las dava um caminho em que
        # o lote repetido contava sem marcar.
        self.cursor.execute(
            "SELECT contactos_vistos, mensagens_vistas, passos_feitos "
            "FROM platform.channel_coexistence "
            "WHERE tenant_id = %s AND channel_id = %s",
            (self.tenant, self.canal),
        )
        contactos, mensagens, passos = self.cursor.fetchone()
        self.assertEqual((contactos, mensagens), (3, 120))
        self.assertEqual(passos, ["historico"])

    def test_um_passo_atrasado_nao_ressuscita_uma_sincronizacao_falhada(self) -> None:
        """O predicado `estado = 'a_sincronizar'` nao e enfeite.

        A Meta reenvia durante sete dias. Sem este predicado, um `history`
        atrasado desfazia o *offboard* que o criterio 3 acabou de pedir.
        """
        self._inserir()
        self.cursor.execute(
            "UPDATE platform.channel_coexistence SET estado = 'falhado' "
            "WHERE tenant_id = %s AND channel_id = %s",
            (self.tenant, self.canal),
        )
        self.cursor.execute(
            "UPDATE platform.channel_coexistence "
            "SET passos_feitos = passos_feitos || 'historico'::text "
            "WHERE tenant_id = %s AND channel_id = %s AND estado = 'a_sincronizar' "
            "  AND NOT ('historico' = ANY (passos_feitos)) RETURNING id",
            (self.tenant, self.canal),
        )
        self.assertEqual(len(self.cursor.fetchall()), 0)

    def test_um_passo_fora_dos_dois_e_recusado(self) -> None:
        self._inserir()
        import pg8000.dbapi

        for invalido in ("verificacao", "CONTACTOS", ""):
            with self.subTest(passo=invalido):
                self.cursor.execute("SAVEPOINT passo_invalido")
                try:
                    with self.assertRaises(pg8000.dbapi.DatabaseError) as capturado:
                        self.cursor.execute(
                            "UPDATE platform.channel_coexistence "
                            "SET passos_feitos = passos_feitos || %s::text "
                            "WHERE tenant_id = %s AND channel_id = %s",
                            (invalido, self.tenant, self.canal),
                        )
                finally:
                    self.cursor.execute("ROLLBACK TO SAVEPOINT passo_invalido")
                self.assertEqual(sqlstate(capturado.exception), VIOLACAO_DE_CHECK)
                self.assertIn(
                    "channel_coexistence_passos_ck", str(capturado.exception)
                )

    def test_os_dois_passos_juntos_passam(self) -> None:
        self._inserir()
        self.cursor.execute(
            "UPDATE platform.channel_coexistence "
            "SET passos_feitos = ARRAY['contactos','historico']::text[] "
            "WHERE tenant_id = %s AND channel_id = %s RETURNING passos_feitos",
            (self.tenant, self.canal),
        )
        self.assertEqual(self.cursor.fetchone()[0], ["contactos", "historico"])

    # ----------------------------------------------------- os dois dominios

    def test_os_quatro_estados_entram(self) -> None:
        for estado in ESTADOS:
            with self.subTest(estado=estado):
                self._inserir(
                    estado=estado,
                    channel_id=factories.canal(self.cursor, self.tenant),
                )

    def test_um_estado_fora_dos_quatro_e_recusado(self) -> None:
        for invalido in ESTADOS_RECUSADOS:
            with self.subTest(estado=invalido):
                self._recusa(
                    VIOLACAO_DE_CHECK,
                    "channel_coexistence_estado_ck",
                    estado=invalido,
                )

    def test_o_dominio_do_estado_bate_com_o_contrato_nos_dois_sentidos(self) -> None:
        """O `CHECK` e a lista do TypeScript tem de ser o **mesmo conjunto**.

        Nos dois sentidos: um valor a mais no `CHECK` e um valor que o codigo
        nunca escreve, e um valor a mais no codigo e um `23514` em producao. E a
        licao que a `0008` e a `0009` pagaram por os deixar divergir.
        """
        definicao = _definicao(self.cursor, "channel_coexistence_estado_ck")
        for estado in ESTADOS:
            self.assertIn(f"'{estado}'", definicao)
        self.assertEqual(definicao.count("::text"), len(ESTADOS))

    def test_os_seis_motivos_entram(self) -> None:
        for motivo in MOTIVOS:
            with self.subTest(motivo=motivo):
                canal = factories.canal(self.cursor, self.tenant)
                self._inserir(
                    channel_id=canal,
                    motivo_desligamento=motivo,
                    desligado_em="now()",
                )

    def test_um_motivo_fora_dos_seis_e_recusado(self) -> None:
        for invalido in MOTIVOS_RECUSADOS:
            with self.subTest(motivo=invalido):
                self._recusa(
                    VIOLACAO_DE_CHECK,
                    "channel_coexistence_motivo_ck",
                    motivo_desligamento=invalido,
                    desligado_em="now()",
                )

    def test_a_forma_da_meta_em_maiusculas_e_recusada_pela_base(self) -> None:
        """O caso que importa dos quatro acima, isolado e com a razao escrita.

        Se `PRIMARY_INACTIVITY` entrasse, a traducao na fronteira deixava de ser
        obrigatoria — e e ela que impede a forma da Meta de chegar ao `outcome`
        de uma linha de registo, onde a gramatica a recusa e, **em modo estrito,
        que e o do CI, o `Logger` levanta**. Um desfecho normal de um webhook
        virava excepcao nao tratada.
        """
        self._recusa(
            VIOLACAO_DE_CHECK,
            "channel_coexistence_motivo_ck",
            motivo_desligamento="PRIMARY_INACTIVITY",
            desligado_em="now()",
        )

    def test_o_dominio_do_motivo_bate_com_o_contrato_nos_dois_sentidos(self) -> None:
        definicao = _definicao(self.cursor, "channel_coexistence_motivo_ck")
        for motivo in MOTIVOS:
            self.assertIn(f"'{motivo}'", definicao)
        self.assertEqual(definicao.count("::text"), len(MOTIVOS))

    # ------------------------------------- o desligamento e uma igualdade

    def test_o_motivo_sem_instante_e_recusado(self) -> None:
        self._recusa(
            VIOLACAO_DE_CHECK,
            "channel_coexistence_desligamento_ck",
            motivo_desligamento="change_number",
        )

    def test_o_instante_sem_motivo_e_recusado(self) -> None:
        self._recusa(
            VIOLACAO_DE_CHECK,
            "channel_coexistence_desligamento_ck",
            desligado_em="now()",
        )

    def test_as_duas_metades_juntas_passam_e_nenhuma_tambem(self) -> None:
        self._inserir()
        self._inserir(
            channel_id=factories.canal(self.cursor, self.tenant),
            motivo_desligamento="change_number",
            desligado_em="now()",
        )

    # --------------------------------------------------- os outros `CHECK`

    def test_o_prazo_tem_de_ser_depois_do_arranque(self) -> None:
        self._recusa(
            VIOLACAO_DE_CHECK,
            "channel_coexistence_prazo_ck",
            prazo_em="now() - interval '1 second'",
        )

    def test_as_contagens_recusam_negativos(self) -> None:
        for coluna in ("contactos_vistos", "mensagens_vistas"):
            with self.subTest(coluna=coluna):
                self._recusa(
                    VIOLACAO_DE_CHECK,
                    "channel_coexistence_contagens_ck",
                    **{coluna: -1},
                )

    # ----------------------------------------------- o isolamento por FK

    def test_a_coexistencia_nao_aponta_para_o_canal_de_outro_tenant(self) -> None:
        """A FK e **composta** com o `tenant_id`, pela razao que a `0009` fixou.

        Sem ela, a coexistencia de A podia apontar para um canal de B — e nem o
        *gate* 6 nem o 3b o veriam, porque a RLS protege a linha e nao o alvo
        da referencia.
        """
        self._recusa(
            VIOLACAO_DE_FK,
            "channel_coexistence_channel_fk",
            channel_id=self.canal_do_outro,
        )

    def test_uma_coexistencia_de_um_tenant_que_nao_existe_e_recusada(self) -> None:
        self._recusa(
            VIOLACAO_DE_FK,
            "channel_coexistence_tenant_fk",
            tenant_id=str(uuid.uuid4()),
            channel_id=self.canal,
        )

    # -------------------------------------------------------- privilegios

    def test_o_kamba_app_le_insere_e_altera(self) -> None:
        """A diferenca face a `channel_onboarding`, e tem razao.

        O onboarding e provisionamento e corre de retaguarda; a coexistencia
        corre no **caminho de um webhook**, e quem trata webhooks e o
        `worker-canal` com o papel `kamba_app` sob RLS `FORCE`.
        """
        self.cursor.execute(
            "SELECT privilege_type FROM information_schema.table_privileges "
            "WHERE table_schema = 'platform' AND table_name = 'channel_coexistence' "
            "  AND grantee = 'kamba_app' ORDER BY 1"
        )
        self.assertEqual(
            [l[0] for l in self.cursor.fetchall()],
            ["INSERT", "SELECT", "UPDATE"],
        )

    def test_o_kamba_app_nao_tem_delete(self) -> None:
        """A regra da `0001`: «soft delete: estado, nunca DELETE»."""
        self.cursor.execute(
            "SELECT has_table_privilege('kamba_app', "
            "'platform.channel_coexistence', 'DELETE')"
        )
        self.assertFalse(self.cursor.fetchone()[0])

    def test_o_kamba_batch_le_e_apaga_e_nao_escreve(self) -> None:
        """**Sem `UPDATE` e sem `INSERT`**, e isso e desenho e nao omissao.

        Nao ha caminho de retaguarda que abra nem altere uma sincronizacao —
        quem a abre e o tratador do `subscrito -> a_sincronizar`, que corre como
        `kamba_app`. Dar-lhe os verbos era abrir um caminho que ninguem pediu.
        """
        self.cursor.execute(
            "SELECT privilege_type FROM information_schema.table_privileges "
            "WHERE table_schema = 'platform' AND table_name = 'channel_coexistence' "
            "  AND grantee = 'kamba_batch' ORDER BY 1"
        )
        self.assertEqual([l[0] for l in self.cursor.fetchall()], ["DELETE", "SELECT"])

    def test_os_papeis_de_leitura_nao_veem_a_tabela(self) -> None:
        for papel in ("kamba_resolver", "kamba_identity", "kamba_audit"):
            with self.subTest(papel=papel):
                self.cursor.execute(
                    "SELECT has_table_privilege(%s, "
                    "'platform.channel_coexistence', 'SELECT')",
                    (papel,),
                )
                self.assertFalse(self.cursor.fetchone()[0])

    # ------------------------------------------------------------ indices

    def test_os_dois_indices_existem_e_o_primeiro_comeca_pelo_tenant(self) -> None:
        self.cursor.execute(
            "SELECT indexname::text, indexdef FROM pg_indexes "
            "WHERE schemaname = 'platform' AND tablename = 'channel_coexistence' "
            "ORDER BY 1"
        )
        indices = dict(self.cursor.fetchall())
        self.assertIn("channel_coexistence_tenant_estado_idx", indices)
        self.assertIn("channel_coexistence_prazo_idx", indices)
        self.assertIn(
            "(tenant_id, estado)", indices["channel_coexistence_tenant_estado_idx"]
        )
        # O segundo **nao** comeca pelo `tenant_id`, e e decisao: a varredura
        # dos prazos nao filtra por tenant e corre com `BYPASSRLS`.
        self.assertIn("(estado, prazo_em)", indices["channel_coexistence_prazo_idx"])

    def test_a_rls_esta_em_force(self) -> None:
        self.cursor.execute(
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
            "WHERE oid = 'platform.channel_coexistence'::regclass"
        )
        self.assertEqual(self.cursor.fetchone(), [True, True])


class TestDowngradeDaCoexistencia(unittest.TestCase):
    """A `0018` desce **com linhas** e nao recusa, e a razao esta na revisao.

    O que se perde e o estado de uma sincronizacao: nao e dinheiro (a `0010`
    recusa descer com linhas) nem prova juridica (a `0015` recusa as duas
    coisas), e uma sincronizacao perdida refaz-se — o dono repete o Embedded
    Signup, que e o que o prazo das 24 h ja manda fazer quando cai.

    Nao herda de `ComBase`: controla ela propria a revisao da base.
    """

    @classmethod
    def setUpClass(cls) -> None:
        if not em_head():
            alembic_ok("upgrade", "head")

    def setUp(self) -> None:
        self.conexao = ligacao.ligar("admin")
        self.conexao.autocommit = True
        self.cursor = self.conexao.cursor()
        self.tenants: list[str] = []

    def tearDown(self) -> None:
        try:
            if not em_head():
                alembic_ok("upgrade", "head")
            for tenant in self.tenants:
                self.cursor.execute(
                    "DELETE FROM platform.channel_coexistence WHERE tenant_id = %s",
                    (tenant,),
                )
                self.cursor.execute(
                    "DELETE FROM platform.tenant_channels WHERE tenant_id = %s",
                    (tenant,),
                )
                self.cursor.execute(
                    "DELETE FROM platform.tenants WHERE id = %s", (tenant,)
                )
        finally:
            self.cursor.close()
            self.conexao.close()

    def test_desce_com_linhas_e_sobe_outra_vez(self) -> None:
        tenant = factories.tenant(self.cursor)
        self.tenants.append(tenant)
        canal = factories.canal(self.cursor, tenant)
        self.cursor.execute(
            "INSERT INTO platform.channel_coexistence "
            "(tenant_id, channel_id, prazo_em) "
            "VALUES (%s, %s, now() + interval '24 hours')",
            (tenant, canal),
        )
        alembic_ok("downgrade", "0017")
        self.assertEqual(_tabelas(self.cursor), TABELAS_ATE_0017)
        alembic_ok("upgrade", "head")
        self.assertEqual(_tabelas(self.cursor), TABELAS)

    def test_a_politica_e_os_indices_voltam_com_a_tabela(self) -> None:
        alembic_ok("downgrade", "0017")
        alembic_ok("upgrade", "head")
        self.cursor.execute(
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
            "WHERE oid = 'platform.channel_coexistence'::regclass"
        )
        self.assertEqual(self.cursor.fetchone(), [True, True])
        self.cursor.execute(
            "SELECT count(*) FROM pg_indexes WHERE schemaname = 'platform' "
            "AND tablename = 'channel_coexistence'"
        )
        # Os dois mais a chave primaria e a unicidade, que tambem sao indices.
        self.assertEqual(self.cursor.fetchone()[0], 4)
