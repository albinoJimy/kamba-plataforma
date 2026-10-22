"""A revisao 0017 contra a base: a tentativa de onboarding de canal (KAM-016).

E a `0017` e nao a `0016`: o KAM-018 reclamou aquele numero e a revisao dele
chegou primeiro ao remoto. A razao esta no docstring da propria revisao.

Cinco coisas, e quatro delas sao criterios do bloco pela letra:

1. **A idempotencia do criterio 2 sao duas unicidades.** A
   `channel_onboarding_code_uq (tenant_id, code_hash)` e a
   `channel_onboarding_tenant_waba_uq (tenant_id, waba_id)` recusam a segunda
   tentativa com `23505` e aceitam-na noutro *tenant*: as duas sao compostas,
   pela razao da emenda 1.21 que a `0015` repetiu.

2. **O 409 do criterio 4 e a unicidade **global** da `0001`.** A
   `tenant_channels_phone_number_id_uq` nao leva `tenant_id`, e e isso que faz
   «um canal pertence a um so tenant» ser propriedade da base. Afirma-se nos
   dois casos que importam: o numero de **outro** tenant e o numero do
   **proprio** tenant — a chave e a mesma, e um 409 que so morde entre tenants
   era uma chave composta disfarcada.

3. **O dominio das nove fases, e o `desligado` que nao e uma delas.** O
   diagrama do `docs/tecnica/01` §13.1 desenha dez estados; o criterio 6
   enumera nove, e o decimo e valor de `tenant_channels.estado` desde a `0001`.
   Afirma-se que o `CHECK` o recusa.

4. **O `channel_onboarding_canal_ck` e uma implicacao e nao uma igualdade.** Nas
   seis fases do meio ha canal; nas tres de fora pode nao haver — e o `falhado`
   **pode** ter canal enquanto a compensacao nao correu. Um `CHECK` sobre as
   seis recusava esse estado legitimo, e ha um teste para cada metade.

5. **O `downgrade`** — «Migracoes reversiveis: `downgrade` testado». Desce com
   linhas e **nao recusa**, e a razao esta na propria revisao: o que se perde e
   o registo de **tentativas**, que nao e dinheiro (a `0010`) nem prova juridica
   (a `0015`) — e as tentativas vivas refazem-se, porque o *code* queima-se e o
   dono repete o *popup*.

A classe do `downgrade` nao herda de `ComBase`: controla ela propria a revisao
da base, e `ComBase` assume `head`.
"""

from __future__ import annotations

import hashlib
import unittest
import uuid

import ligacao
from tests import factories
from tests.base import (
    PRIVILEGIO_INSUFICIENTE,
    TABELAS,
    TABELAS_ATE_0016,
    VIOLACAO_DE_CHECK,
    VIOLACAO_DE_FK,
    VIOLACAO_DE_UNICIDADE,
    ComBase,
    alembic_ok,
    em_head,
    sqlstate,
)

#: As nove fases, como a revisao as declara e como o dicionario §3.20 as fixa
#: (emenda 1.29). **O `desligado` nao esta aqui**: e estado de
#: `tenant_channels` e nao fase de onboarding, e quem o escreve e o KAM-017.
FASES = (
    "iniciado",
    "es_concluido",
    "subscrito",
    "a_sincronizar",
    "verificado",
    "pronto",
    "ativo",
    "falhado",
    "abandonado",
)

#: As seis fases em que **ja existe canal**: o `channel_onboarding_canal_ck`
#: exige `channel_id` em todas elas.
FASES_COM_CANAL = (
    "es_concluido",
    "subscrito",
    "a_sincronizar",
    "verificado",
    "pronto",
    "ativo",
)

#: As tres em que o `channel_id` pode ser nulo. O `falhado` esta aqui **e** pode
#: ter canal: a implicacao e num sentido so.
FASES_SEM_CANAL = ("iniciado", "falhado", "abandonado")

#: Valores que o `CHECK` do dominio tem de recusar. O primeiro e o decimo estado
#: do diagrama; o segundo e terceiro sao valores de `tenant_channels.estado`; o
#: quarto e a mesma fase com outra caixa, e o `§2` do dicionario manda
#: minusculas; o quinto e a cadeia vazia.
FASES_RECUSADAS = ("desligado", "pendente", "suspenso", "INICIADO", "")

#: Trinta e dois octetos: o tamanho de um `sha256`, que e o unico que o
#: `channel_onboarding_code_hash_ck` aceita.
RESUMO = bytes(range(32))


def _resumo(semente: str) -> bytes:
    return hashlib.sha256(semente.encode("ascii")).digest()


def _tabelas(cursor) -> tuple[str, ...]:
    cursor.execute(
        "SELECT tablename::text FROM pg_tables WHERE schemaname = 'platform' ORDER BY 1"
    )
    return tuple(linha[0] for linha in cursor.fetchall())


class TestTentativaDeOnboarding(ComBase):
    """O que o DDL da `0017` promete.

    `ComBase` da uma ligacao que **nunca confirma**: cada teste desfaz o que
    escreveu, e e por isso que o tenant e o canal se semeiam em cada um.
    """

    def setUp(self) -> None:
        super().setUp()
        self.conexao = self.ligar("admin")
        self.cursor = self.conexao.cursor()
        self.tenant = factories.tenant(self.cursor)
        self.outro = factories.tenant(self.cursor)

    def _campos(self, **troca) -> dict:
        """Os campos obrigatorios, com os dois identificadores unicos por chamada.

        **O `code_hash` deriva do `waba_id`**, e isso foi uma correccao que o
        gate 8 fez: a primeira versao usava a constante `RESUMO` em todas as
        inserções, pelo que a segunda linha de um teste batia na
        `channel_onboarding_code_uq` **antes** de bater na chave que o teste
        queria medir — o `test_o_mesmo_waba_no_mesmo_tenant_e_recusado` falhava
        a dizer `channel_onboarding_code_uq`, que e a restricao certa pela razao
        errada. Duas unicidades sobre a mesma tabela obrigam a que um teste de
        uma delas varie a outra.
        """
        campos = {
            "tenant_id": self.tenant,
            "waba_id": f"waba-{uuid.uuid4().hex[:8]}",
            "phone_number_id": f"pnid-{uuid.uuid4()}",
        }
        campos.update(troca)
        campos.setdefault("code_hash", _resumo(str(campos["waba_id"])))
        return campos

    def _inserir(self, **troca):
        campos = self._campos(**troca)
        colunas = ", ".join(campos)
        marcas = ", ".join(["%s"] * len(campos))
        self.cursor.execute(
            f"INSERT INTO platform.channel_onboarding ({colunas}) "
            f"VALUES ({marcas}) RETURNING id::text",
            tuple(campos.values()),
        )
        return self.cursor.fetchone()[0]

    def _recusa(self, sqlstate_esperado: str, restricao: str, **troca) -> None:
        """A insercao tem de falhar, com o SQLSTATE e a restricao esperados.

        **Pelo `assertErroSql` do `ComBase`, que corre dentro de um
        `SAVEPOINT`**, e isso nao e cerimonia: um erro aborta a transaccao
        inteira no PostgreSQL, e sem o ponto de salvaguarda o **segundo** caso
        negativo de um `subTest` falhava com `25P02` («current transaction is
        aborted») em vez da violacao que se queria medir. A primeira versao
        desta bateria usava `assertRaises` directamente, e o gate 8 devolveu
        trinta e seis falhas — trinta e tres delas eram este defeito a repetir-se
        por cada caso de cada ciclo. O ajudante e do KAM-022, que pagou a mesma
        licao, e o `docstring` dele ja o dizia.

        A restricao confere-se **depois**, sobre a excepcao: o `assertErroSql`
        verifica o SQLSTATE e nao o nome, e um `23514` da restricao errada e um
        teste verde a medir outra coisa.
        """
        import pg8000.dbapi

        campos = self._campos(**troca)
        colunas = ", ".join(campos)
        marcas = ", ".join(["%s"] * len(campos))
        sql = (
            f"INSERT INTO platform.channel_onboarding ({colunas}) "
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

    def test_a_linha_nasce_em_iniciado_sem_canal_e_sem_recursos(self) -> None:
        identificador = self._inserir()
        self.cursor.execute(
            "SELECT fase, channel_id, recursos_criados, pin_ref, motivo, waac_id "
            "FROM platform.channel_onboarding WHERE id = %s",
            (identificador,),
        )
        fase, canal, recursos, pin, motivo, waac = self.cursor.fetchone()
        self.assertEqual(fase, "iniciado")
        self.assertIsNone(canal)
        self.assertEqual(recursos, [])
        self.assertIsNone(pin)
        self.assertIsNone(motivo)
        # Nulo **de proposito**: a Fase 3 do novo modelo de contas (H1 2028)
        # passa a exigir o ID do WAAC nos caminhos da API.
        self.assertIsNone(waac)

    def test_o_id_e_um_uuid_gerado(self) -> None:
        # O `kamba_app` **le** esta tabela, e com um `id` sequencial esse papel
        # media quantos clientes novos a plataforma esta a ligar — que e
        # exactamente o numero que o tecto de dez em sete dias mede.
        self.assertNotEqual(self._inserir(), self._inserir())

    # ------------------------------------------- a idempotencia do criterio 2

    def test_o_mesmo_code_no_mesmo_tenant_e_recusado(self) -> None:
        self._inserir(code_hash=_resumo("um-code"))
        # O `waba_id` varia (e a omissao do `_campos`), pelo que o que morde e a
        # chave do *code* e nao a do WABA.
        self._recusa(
            VIOLACAO_DE_UNICIDADE,
            "channel_onboarding_code_uq",
            code_hash=_resumo("um-code"),
        )

    def test_o_mesmo_code_noutro_tenant_entra(self) -> None:
        # A chave e composta com o `tenant_id`, pela razao da emenda 1.21: com
        # unicidade global, uma tentativa de B que calhasse no mesmo resumo era
        # deduplicada em silencio contra a de A.
        self._inserir(code_hash=_resumo("partilhado"))
        self._inserir(tenant_id=self.outro, code_hash=_resumo("partilhado"))

    def test_o_mesmo_waba_no_mesmo_tenant_e_recusado(self) -> None:
        self._inserir(waba_id="waba-repetido")
        # **O `code_hash` tem de variar**, e e a correccao do `_campos`: com o
        # mesmo resumo, a `channel_onboarding_code_uq` mordia primeiro e o teste
        # ficava verde a medir a outra chave.
        self._recusa(
            VIOLACAO_DE_UNICIDADE,
            "channel_onboarding_tenant_waba_uq",
            waba_id="waba-repetido",
            code_hash=_resumo("outro-code"),
        )

    def test_o_mesmo_waba_noutro_tenant_entra(self) -> None:
        self._inserir(waba_id="waba-partilhado")
        self._inserir(tenant_id=self.outro, waba_id="waba-partilhado")

    # ------------------------------------------------- o 409 do criterio 4

    def test_o_phone_number_id_de_outro_tenant_e_recusado_pela_0001(self) -> None:
        """**O 409 e a unicidade global a morder**, e nao uma verificacao em codigo."""
        canal = factories.canal(self.cursor, self.tenant)
        self.cursor.execute(
            "SELECT phone_number_id FROM platform.tenant_channels WHERE id = %s",
            (canal,),
        )
        numero = self.cursor.fetchone()[0]
        with self.assertRaises(Exception) as erro:
            factories.canal(self.cursor, self.outro, phone_number_id=numero)
        self.assertEqual(sqlstate(erro.exception), VIOLACAO_DE_UNICIDADE)
        self.assertIn("tenant_channels_phone_number_id_uq", str(erro.exception))

    def test_o_phone_number_id_do_proprio_tenant_tambem_e_recusado(self) -> None:
        """A chave e **global**: um 409 que so morde entre tenants era composta."""
        canal = factories.canal(self.cursor, self.tenant)
        self.cursor.execute(
            "SELECT phone_number_id FROM platform.tenant_channels WHERE id = %s",
            (canal,),
        )
        numero = self.cursor.fetchone()[0]
        with self.assertRaises(Exception) as erro:
            factories.canal(self.cursor, self.tenant, phone_number_id=numero)
        self.assertEqual(sqlstate(erro.exception), VIOLACAO_DE_UNICIDADE)

    # -------------------------------------------- o dominio das nove fases

    def test_as_nove_fases_entram(self) -> None:
        canal = factories.canal(self.cursor, self.tenant)
        factories.contexto(self.cursor, self.tenant)
        for fase in FASES:
            with self.subTest(fase=fase):
                self._inserir(
                    waba_id=f"waba-{fase}",
                    code_hash=_resumo(fase),
                    fase=fase,
                    # As seis do meio exigem canal; as tres de fora aceitam-no.
                    channel_id=canal,
                )

    def test_uma_fase_fora_das_nove_e_recusada(self) -> None:
        """**Com canal**, e isso nao e detalhe: sao dois `CHECK` sobre a mesma linha.

        A primeira versao inseria sem `channel_id`, e o PostgreSQL recusava pelo
        `channel_onboarding_canal_ck` — correctamente, porque uma fase fora das
        nove tambem nao esta nas tres que dispensam canal. A linha **era**
        recusada, mas pela outra restricao, e a assercao sobre o nome ficava
        vermelha. A ordem de avaliacao de dois `CHECK` nao e garantida, pelo que
        a unica forma de afirmar **qual** morde e deixar so um por morder: com
        canal, o `canal_ck` esta satisfeito e o que sobra e o dominio.
        """
        canal = factories.canal(self.cursor, self.tenant)
        factories.contexto(self.cursor, self.tenant)
        for fase in FASES_RECUSADAS:
            with self.subTest(fase=fase):
                self._recusa(
                    VIOLACAO_DE_CHECK,
                    "channel_onboarding_fase_ck",
                    waba_id=f"waba-{fase or 'vazia'}",
                    fase=fase,
                    channel_id=canal,
                )

    # ------------------------------------------- a implicacao do channel_id

    def test_as_seis_fases_do_meio_exigem_canal(self) -> None:
        for fase in FASES_COM_CANAL:
            with self.subTest(fase=fase):
                self._recusa(
                    VIOLACAO_DE_CHECK,
                    "channel_onboarding_canal_ck",
                    waba_id=f"waba-sem-canal-{fase}",
                    fase=fase,
                )

    def test_as_tres_fases_de_fora_passam_sem_canal(self) -> None:
        for fase in FASES_SEM_CANAL:
            with self.subTest(fase=fase):
                self._inserir(
                    waba_id=f"waba-nulo-{fase}",
                    code_hash=_resumo(f"nulo-{fase}"),
                    fase=fase,
                )

    def test_o_falhado_pode_ter_canal_e_a_implicacao_e_num_sentido_so(self) -> None:
        """Enquanto a compensacao nao correu, o `falhado` **tem** canal."""
        canal = factories.canal(self.cursor, self.tenant)
        factories.contexto(self.cursor, self.tenant)
        self._inserir(fase="falhado", channel_id=canal)

    # ------------------------------------------------------- as FK compostas

    def test_uma_tentativa_nao_aponta_para_o_canal_de_outro_tenant(self) -> None:
        canal = factories.canal(self.cursor, self.outro)
        # O `factories.canal` deixa o contexto no tenant que recebeu; repoe-se o
        # do teste, senao o `INSERT` corre com o contexto errado.
        factories.contexto(self.cursor, self.tenant)
        self._recusa(
            VIOLACAO_DE_FK,
            "channel_onboarding_channel_fk",
            fase="es_concluido",
            channel_id=canal,
        )

    def test_uma_tentativa_de_um_tenant_que_nao_existe_e_recusada(self) -> None:
        self._recusa(
            VIOLACAO_DE_FK,
            "channel_onboarding_tenant_fk",
            tenant_id=str(uuid.uuid4()),
        )

    # ------------------------------------------------- os CHECK de forma

    def test_o_code_hash_exige_trinta_e_dois_octetos(self) -> None:
        for tamanho in (0, 16, 31, 33, 64):
            with self.subTest(tamanho=tamanho):
                self._recusa(
                    VIOLACAO_DE_CHECK,
                    "channel_onboarding_code_hash_ck",
                    waba_id=f"waba-hash-{tamanho}",
                    code_hash=bytes(tamanho),
                )

    def test_o_recursos_criados_exige_um_array(self) -> None:
        for indice, valor in enumerate(('{}', '{"a": 1}', '"cadeia"', "1", "true", "null")):
            with self.subTest(valor=valor):
                self._recusa(
                    VIOLACAO_DE_CHECK,
                    "channel_onboarding_recursos_ck",
                    waba_id=f"waba-jsonb-{indice}",
                    recursos_criados=valor,
                )

    def test_o_pin_ref_exige_a_forma_de_uma_secret_ref(self) -> None:
        # **A forma e nao «nao vazio»**: uma referencia mal formada e um segredo
        # que ninguem vai conseguir ir buscar, e isso descobre-se no dia em que
        # faz falta.
        for indice, ref in enumerate(("123456", "MAIUSCULAS/x", "a/b", "", " ", "meta pin/x")):
            with self.subTest(ref=ref):
                self._recusa(
                    VIOLACAO_DE_CHECK,
                    "channel_onboarding_pin_ref_ck",
                    waba_id=f"waba-pin-{indice}",
                    pin_ref=ref,
                )

    def test_o_pin_ref_bem_formado_passa(self) -> None:
        self._inserir(pin_ref="meta_pin_2fa/" + "0" * 32)

    def test_os_identificadores_recusam_vazio_e_espacos_a_volta(self) -> None:
        casos = (
            ("waba_id", "channel_onboarding_waba_id_ck", ("", " waba", "waba ")),
            (
                "phone_number_id",
                "channel_onboarding_phone_number_id_ck",
                ("", " pnid", "pnid "),
            ),
            ("waac_id", "channel_onboarding_waac_id_ck", ("", " waac", "waac ")),
            ("motivo", "channel_onboarding_motivo_ck", ("", "   ")),
        )
        for coluna, restricao, valores in casos:
            for indice, valor in enumerate(valores):
                with self.subTest(coluna=coluna, valor=valor):
                    campos = {"waba_id": f"waba-{coluna}-{indice}", coluna: valor}
                    self._recusa(VIOLACAO_DE_CHECK, restricao, **campos)

    # ------------------------------------------------------- os privilegios

    def test_o_kamba_app_le_e_nao_escreve_nada(self) -> None:
        """**O privilegio nem existe**, que e mais forte do que a politica recusar.

        E a **primeira** tabela deste esquema em que o `kamba_app` le e nao
        escreve: a `message_templates` le e altera, a `events_dlq` escreve e nao
        le. A razao e que o onboarding de um canal e provisionamento, e quem
        provisiona e o `kamba_batch` (dicionario §3.2).

        **Com a metade positiva primeiro**, sem a qual uma concessao em falta
        por inteiro passava as tres negativas.
        """
        app = self.ligar("app")
        cursor = app.cursor()
        factories.contexto(cursor, self.tenant)
        # A metade positiva: o `SELECT` existe.
        cursor.execute("SELECT count(*) FROM platform.channel_onboarding")
        self.assertEqual(cursor.fetchone()[0], 0)
        for instrucao, valores in (
            (
                "INSERT INTO platform.channel_onboarding "
                "(tenant_id, waba_id, phone_number_id, code_hash) "
                "VALUES (%s, 'w', 'p', %s)",
                (self.tenant, RESUMO),
            ),
            ("UPDATE platform.channel_onboarding SET fase = 'falhado'", ()),
            ("DELETE FROM platform.channel_onboarding", ()),
        ):
            with self.subTest(instrucao=instrucao.split()[0]):
                with self.assertRaises(Exception) as erro:
                    cursor.execute(instrucao, valores)
                self.assertEqual(sqlstate(erro.exception), PRIVILEGIO_INSUFICIENTE)
                app.rollback()
                factories.contexto(cursor, self.tenant)

    def test_o_kamba_batch_tem_os_quatro_verbos(self) -> None:
        """A metade positiva do privilegio, e **o tenant e desta ligacao**.

        A primeira versao semeava o tenant com o cursor de administrador e
        inseria com o de `kamba_batch`: `23503` na FK, porque **a ligacao do
        `ComBase` nunca confirma** e a segunda sessao nao ve o que a primeira
        escreveu. E a mesma licao que o KAM-022 registou, pelo outro lado — ali
        era uma contagem que nao via as linhas, aqui e uma FK que nao ve o pai.
        O `kamba_batch` tem os quatro verbos em `tenants` desde a `0001`, pelo
        que pode semear o seu.
        """
        batch = self.ligar("batch")
        cursor = batch.cursor()
        tenant = factories.tenant(cursor)
        cursor.execute(
            "INSERT INTO platform.channel_onboarding "
            "(tenant_id, waba_id, phone_number_id, code_hash) "
            "VALUES (%s, %s, %s, %s) RETURNING id::text",
            (tenant, f"waba-{uuid.uuid4().hex[:8]}", f"pnid-{uuid.uuid4()}", RESUMO),
        )
        identificador = cursor.fetchone()[0]
        cursor.execute(
            "UPDATE platform.channel_onboarding SET fase = 'falhado' WHERE id = %s",
            (identificador,),
        )
        cursor.execute(
            "SELECT count(*) FROM platform.channel_onboarding WHERE id = %s",
            (identificador,),
        )
        self.assertEqual(cursor.fetchone()[0], 1)
        cursor.execute(
            "DELETE FROM platform.channel_onboarding WHERE id = %s", (identificador,)
        )
        cursor.execute(
            "SELECT count(*) FROM platform.channel_onboarding WHERE id = %s",
            (identificador,),
        )
        self.assertEqual(cursor.fetchone()[0], 0)

    # ------------------------------------------------------------- os indices

    def test_os_tres_indices_existem_e_o_primeiro_comeca_pelo_tenant(self) -> None:
        """O `tenant_id` primeiro **porque a RLS o le em toda a consulta**.

        A licao e da `0011`, onde o gate 8 recusou a tabela sem ele. Os outros
        dois **nao** levam `tenant_id` a frente, e isso e decisao: as duas
        perguntas que respondem — quantos onboardings houve na plataforma nos
        ultimos sete dias, e quais estao parados ha mais de 30 minutos — nao
        filtram por tenant, e quem as faz tem `BYPASSRLS`.
        """
        self.cursor.execute(
            "SELECT indexname::text, indexdef::text FROM pg_indexes "
            "WHERE schemaname = 'platform' AND tablename = 'channel_onboarding' "
            "ORDER BY 1"
        )
        indices = dict(self.cursor.fetchall())
        self.assertEqual(
            sorted(indices),
            [
                "channel_onboarding_code_uq",
                "channel_onboarding_espera_idx",
                "channel_onboarding_janela_idx",
                "channel_onboarding_pkey",
                "channel_onboarding_tenant_fase_idx",
                "channel_onboarding_tenant_waba_uq",
            ],
        )
        self.assertIn("(tenant_id, fase)", indices["channel_onboarding_tenant_fase_idx"])
        self.assertIn("criado_at DESC", indices["channel_onboarding_janela_idx"])
        self.assertIn("(fase, actualizado_at)", indices["channel_onboarding_espera_idx"])


class TestDowngradeDa0017(unittest.TestCase):
    """Desce com linhas e sobe outra vez, e **nao recusa**.

    A razao esta na revisao, e nao e a da `0015`: o que se perde e o registo de
    **tentativas** de onboarding, que nao e dinheiro (a guarda da `0010`) nem
    prova juridica (a recusa da `0015`). As tentativas vivas refazem-se — o
    *code* queima-se e o dono repete o *popup* —, e **os canais nao se perdem**:
    a linha de `tenant_channels` e da `0001` e fica onde esta.
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
                    "DELETE FROM platform.channel_onboarding WHERE tenant_id = %s",
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
            self.conexao.close()

    def test_desce_com_linhas_e_sobe_outra_vez(self) -> None:
        tenant = factories.tenant(self.cursor)
        self.tenants.append(tenant)
        canal = factories.canal(self.cursor, tenant)
        self.cursor.execute(
            "INSERT INTO platform.channel_onboarding "
            "(tenant_id, channel_id, waba_id, phone_number_id, code_hash, fase) "
            "VALUES (%s, %s, 'waba-descida', 'pnid-descida', %s, 'subscrito')",
            (tenant, canal, RESUMO),
        )
        self.assertEqual(_tabelas(self.cursor), TABELAS)

        alembic_ok("downgrade", "0016")
        # A tabela desapareceu, e **o canal ficou**: ele e da `0001`.
        self.assertEqual(_tabelas(self.cursor), TABELAS_ATE_0016)
        self.cursor.execute(
            "SELECT count(*) FROM platform.tenant_channels WHERE id = %s", (canal,)
        )
        self.assertEqual(self.cursor.fetchone()[0], 1)

        alembic_ok("upgrade", "head")
        self.assertEqual(_tabelas(self.cursor), TABELAS)
        # E a tentativa nao voltou: a tabela e nova.
        self.cursor.execute(
            "SELECT count(*) FROM platform.channel_onboarding WHERE tenant_id = %s",
            (tenant,),
        )
        self.assertEqual(self.cursor.fetchone()[0], 0)

    def test_a_politica_e_os_indices_voltam_com_a_tabela(self) -> None:
        """O `downgrade` nao deixa a politica pendurada, e o `upgrade` repoe-a.

        Sem isto, uma base que desca e volte a subir ficava com a tabela e **sem
        RLS** — e o gate 6 so a veria no proximo `make ci-6`, contra uma base
        levantada de `base` e nao de um ciclo.
        """
        alembic_ok("downgrade", "0016")
        self.cursor.execute(
            "SELECT count(*) FROM pg_policies "
            "WHERE schemaname = 'platform' AND tablename = 'channel_onboarding'"
        )
        self.assertEqual(self.cursor.fetchone()[0], 0)

        alembic_ok("upgrade", "head")
        self.cursor.execute(
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'platform' AND c.relname = 'channel_onboarding'"
        )
        self.assertEqual(tuple(self.cursor.fetchone()), (True, True))
        self.cursor.execute(
            "SELECT count(*) FROM pg_policies WHERE schemaname = 'platform' "
            "AND tablename = 'channel_onboarding' AND policyname = 'tenant_iso'"
        )
        self.assertEqual(self.cursor.fetchone()[0], 1)
        self.cursor.execute(
            "SELECT count(*) FROM pg_indexes WHERE schemaname = 'platform' "
            "AND tablename = 'channel_onboarding'"
        )
        self.assertEqual(self.cursor.fetchone()[0], 6)
