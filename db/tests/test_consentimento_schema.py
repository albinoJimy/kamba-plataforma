"""A revisao 0015 contra a base: a prova, o texto e a primeira vista (KAM-022).

Quatro coisas, e duas delas sao criterios do bloco pela letra:

1. **O *append-only* e um privilegio e nao uma politica.** «`UPDATE/DELETE`
   recusados para `kamba_app`» (criterio 6): afirma-se o **`42501`** nos dois
   verbos e nas duas tabelas, e afirma-se a metade positiva — o `SELECT` e o
   `INSERT` funcionam —, sem a qual uma concessao em falta por inteiro passava
   as negativas. Um teste do lado do codigo prova o que o codigo faz hoje; este
   prova o que nenhum codigo pode fazer.

2. **A vista leva `security_invoker = true`.** E a **primeira vista do
   esquema**, e o `verificar_vistas` do `db/tests_isolamento/catalogo.py` existe
   desde o KAM-004 a exigi-lo sem nunca ter tido nada para ver. Aqui prova-se
   duas vezes: a opcao esta na relacao, e a vista **respeita a RLS** — com o
   contexto de A, o estado de B nao aparece nela. Sem `security_invoker`, uma
   vista corre com os privilegios do dono e a RLS passava a depender do `FORCE`.

3. **A idempotencia do criterio 2 e da base.** A
   `consent_event_prova_uq (tenant_id, contact_id, purpose, evidence_hash)`
   recusa a segunda prova do mesmo botao com `23505`, e aceita-a noutro
   *tenant*: a chave e composta, pela razao da emenda 1.21.

4. **O `downgrade`** — «Migracoes reversiveis: `downgrade` testado». Desce com
   linhas, e **nao recusa**: a razao esta na propria revisao, e nao e que a
   prova valha pouco — e que uma copia para ficheiro, que e o que a `0010` e a
   `0012` fazem, era guardar prova juridica fora do esquema, sem RLS e sem
   retencao.

A classe do `downgrade` nao herda de `ComBase`: controla ela propria a revisao
da base, e `ComBase` assume `head`.
"""

from __future__ import annotations

import pathlib
import re
import unittest

import ligacao
from tests import factories
from tests.base import (
    PRIVILEGIO_INSUFICIENTE,
    TABELAS,
    TABELAS_ATE_0014,
    VIOLACAO_DE_CHECK,
    VIOLACAO_DE_FK,
    VIOLACAO_DE_NOT_NULL,
    VIOLACAO_DE_UNICIDADE,
    VISTAS,
    ComBase,
    alembic_ok,
    em_head,
    sqlstate,
)

#: Os SQLSTATE que os casos negativos esperam, pelos nomes que o `base.py` ja
#: declara. **O `sqlstate()` tambem e dele**, e a primeira versao desta bateria
#: nao o usou: inventou um `excepcao.sqlstate`, que o pg8000 nao tem — o codigo
#: vem no campo `C` do dicionario da mensagem do servidor. Dezasseis erros, e o
#: gate 8 apanhou-os todos a primeira volta.
CHECK_VIOLATION = VIOLACAO_DE_CHECK
UNIQUE_VIOLATION = VIOLACAO_DE_UNICIDADE
FK_VIOLATION = VIOLACAO_DE_FK
NOT_NULL_VIOLATION = VIOLACAO_DE_NOT_NULL

#: As dez finalidades, como a revisao as declara e como o dicionario §3.1 as
#: fixou (emenda 1.16, KAM-159). Sao a **uniao** das cinco que o dicionario
#: nomeava e das oito dos contratos publicados, que se cruzavam numa so.
FINALIDADES = (
    "transacao",
    "atendimento",
    "marketing",
    "analytics_agregado",
    "melhoria_servico",
    "sugestoes_patrocinadas",
    "partilha_loja",
    "partilha_parceiros",
    "partilha_estafeta",
    "notificacao_dono",
)

#: Trinta e dois octetos: o tamanho de um `sha256`, que e o unico que o
#: `consent_event_evidence_ck` aceita.
PROVA = bytes(range(32))


def _tabelas(cursor) -> tuple[str, ...]:
    cursor.execute(
        "SELECT tablename::text FROM pg_tables WHERE schemaname = 'platform' ORDER BY 1"
    )
    return tuple(linha[0] for linha in cursor.fetchall())


def _vistas(cursor) -> tuple[str, ...]:
    cursor.execute(
        "SELECT viewname::text FROM pg_views WHERE schemaname = 'platform' ORDER BY 1"
    )
    return tuple(linha[0] for linha in cursor.fetchall())


class TestProvaDeConsentimento(ComBase):
    """O que o DDL da `0015` promete.

    `ComBase` da uma ligacao que **nunca confirma**: cada teste desfaz o que
    escreveu, e e por isso que o tenant e o contacto se semeiam em cada um.
    """

    def setUp(self) -> None:
        super().setUp()
        self.conexao = self.ligar("admin")
        self.cursor = self.conexao.cursor()
        self.tenant = factories.tenant(self.cursor)
        self.contacto = factories.contacto(self.cursor, self.tenant)

    def _inserir(self, **troca):
        campos = {
            "tenant_id": self.tenant,
            "contact_id": self.contacto,
            "purpose": "transacao",
            "text_version": "v1",
            "accepted": True,
            "canal": "whatsapp",
            "evidence_hash": PROVA,
        }
        campos.update(troca)
        self.cursor.execute(
            "INSERT INTO platform.consent_event "
            "(tenant_id, contact_id, purpose, text_version, accepted, canal, "
            " evidence_hash) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (
                campos["tenant_id"],
                campos["contact_id"],
                campos["purpose"],
                campos["text_version"],
                campos["accepted"],
                campos["canal"],
                campos["evidence_hash"],
            ),
        )
        return self.cursor.fetchone()[0]

    # ------------------------------------------------------------- o dominio

    def test_as_dez_finalidades_do_dominio_passam(self) -> None:
        """Dez, e e a uniao das duas listas que existiam (KAM-159)."""
        for indice, finalidade in enumerate(FINALIDADES):
            with self.subTest(finalidade=finalidade):
                # `evidence_hash` diferente por finalidade: a unicidade e por
                # `(tenant, contacto, finalidade, prova)` e o mesmo trio com a
                # mesma prova bateria nela. Uma prova por linha e tambem o caso
                # real: cada aviso mostrado tem o seu resumo.
                self._inserir(
                    purpose=finalidade,
                    evidence_hash=bytes([indice]) + PROVA[1:],
                )

    def test_uma_finalidade_fora_do_dominio_e_recusada(self) -> None:
        with self.assertRaises(Exception) as capturado:
            self._inserir(purpose="publicidade")
        self.assertEqual(sqlstate(capturado.exception), CHECK_VIOLATION)

    def test_o_canal_e_um_dominio_de_um_valor(self) -> None:
        """Um e nao zero: o segundo transporte entra por migracao."""
        with self.assertRaises(Exception) as capturado:
            self._inserir(canal="sms")
        self.assertEqual(sqlstate(capturado.exception), CHECK_VIOLATION)

    # --------------------------------------------------------- a forma da prova

    def test_um_resumo_de_outro_tamanho_e_recusado(self) -> None:
        """**Trinta e dois octetos, nem mais nem menos.**

        Um `evidence_hash` de outro tamanho nao e um `sha256`, e uma prova que
        nao se sabe reproduzir nao e prova. Os dois lados: curto e longo.
        """
        for prova in (PROVA[:31], PROVA + b"\x00"):
            with self.subTest(octetos=len(prova)):
                with self.assertRaises(Exception) as capturado:
                    self._inserir(evidence_hash=prova)
                self.assertEqual(sqlstate(capturado.exception), CHECK_VIOLATION)
                self.conexao.rollback()

    def test_uma_versao_de_texto_vazia_e_recusada(self) -> None:
        with self.assertRaises(Exception) as capturado:
            self._inserir(text_version="   ")
        self.assertEqual(sqlstate(capturado.exception), CHECK_VIOLATION)

    def test_o_accepted_nao_tem_terceiro_estado(self) -> None:
        """E `boolean NOT NULL`: «nao respondeu» nao e uma linha desta tabela.

        O `06` §7.3 tinha um `estado` tri-estado, e o KAM-140 reconciliou-o no
        booleano do `10` §7.2. A diferenca nao e de forma: um consentimento que
        ainda nao foi dado **nao tem linha**, e e a ausencia que o `ConsentGate`
        le. Um terceiro estado punha a ausencia e o «nao» a parecer a mesma
        coisa.
        """
        with self.assertRaises(Exception) as capturado:
            self._inserir(accepted=None)
        self.assertEqual(sqlstate(capturado.exception), NOT_NULL_VIOLATION)

    # ------------------------------------------- a idempotencia do criterio 2

    def test_a_mesma_prova_duas_vezes_e_recusada(self) -> None:
        """«O mesmo botao repetido 2x produz 1 linha», e e da base.

        A prova e `sha256(texto || contact_id || wamid || hora)` com o `wamid` e
        a hora **da Meta**: uma reentrega do mesmo *webhook* produz o mesmo
        resumo e bate aqui.
        """
        self._inserir()
        with self.assertRaises(Exception) as capturado:
            self._inserir()
        self.assertEqual(sqlstate(capturado.exception), UNIQUE_VIOLATION)

    def test_a_mesma_prova_em_dois_tenants_da_duas_linhas(self) -> None:
        """A unicidade e **composta** com o `tenant_id` (emenda 1.21).

        Com unicidade global, uma prova do *tenant* B que calhasse no mesmo
        resumo era deduplicada em silencio contra uma linha de A — e aqui o que
        se perdia era prova juridica.
        """
        self._inserir()
        outro = factories.tenant(self.cursor)
        contacto = factories.contacto(self.cursor, outro)
        self._inserir(tenant_id=outro, contact_id=contacto)
        self.cursor.execute(
            "SELECT count(*) FROM platform.consent_event WHERE evidence_hash = %s",
            (PROVA,),
        )
        self.assertEqual(self.cursor.fetchone()[0], 2)

    def test_a_revogacao_e_uma_linha_nova_e_nao_uma_correccao(self) -> None:
        """«Revogacao = nova linha», e a prova diferente e o que a deixa entrar."""
        self._inserir(purpose="marketing", accepted=True)
        self._inserir(
            purpose="marketing", accepted=False, evidence_hash=b"\xff" + PROVA[1:]
        )
        self.cursor.execute(
            "SELECT count(*) FROM platform.consent_event "
            "WHERE tenant_id = %s AND purpose = 'marketing'",
            (self.tenant,),
        )
        self.assertEqual(self.cursor.fetchone()[0], 2)

    # ---------------------------------------------------------------- as FK

    def test_a_fk_do_contacto_leva_o_tenant(self) -> None:
        """Sem ela, uma prova de A apontava para um contacto de B.

        A RLS protege a **leitura**; a integridade e da FK, e esta e composta
        pela razao que a `0009` fixou.
        """
        outro = factories.tenant(self.cursor)
        contacto_de_b = factories.contacto(self.cursor, outro)
        with self.assertRaises(Exception) as capturado:
            self._inserir(contact_id=contacto_de_b)
        self.assertEqual(sqlstate(capturado.exception), FK_VIOLATION)

    # ------------------------------------------------------------ a vista

    def test_a_vista_existe_e_leva_security_invoker(self) -> None:
        """**A primeira vista do esquema**, e a opcao nao e decorativa.

        Uma vista corre, por omissao, com os privilegios do dono, e o dono esta
        sujeito a RLS **so por causa do `FORCE`**. Com `security_invoker` a
        vista corre como quem a consulta, que e o que a politica pressupoe. O
        `verificar_vistas` do catalogo do X-05 exige-o para qualquer vista, sem
        lista de excepcoes; aqui afirma-se para esta.
        """
        self.assertEqual(_vistas(self.cursor), VISTAS)
        self.cursor.execute(
            "SELECT COALESCE(reloptions, '{}') FROM pg_class "
            "WHERE oid = 'platform.consent_actual'::regclass"
        )
        opcoes = [str(o).replace(" ", "").lower() for o in self.cursor.fetchone()[0]]
        self.assertIn("security_invoker=true", opcoes)

    def test_a_vista_devolve_a_ultima_linha_do_trio(self) -> None:
        """«O ultimo estado por (tenant, contact, purpose)», e e o criterio 6.

        Duas linhas de `marketing` com instantes diferentes: a vista devolve a
        **segunda**, e uma so.
        """
        self._inserir(
            purpose="marketing", accepted=True, evidence_hash=b"\x01" + PROVA[1:]
        )
        self.cursor.execute(
            "UPDATE platform.consent_event SET ocorrido_em = now() - interval '1 day' "
            "WHERE tenant_id = %s",
            (self.tenant,),
        )
        self._inserir(
            purpose="marketing", accepted=False, evidence_hash=b"\x02" + PROVA[1:]
        )
        self.cursor.execute(
            "SELECT accepted FROM platform.consent_actual "
            "WHERE tenant_id = %s AND contact_id = %s AND purpose = 'marketing'",
            (self.tenant, self.contacto),
        )
        linhas = self.cursor.fetchall()
        # **Uma linha, e o valor da ultima.** Compara-se o conteudo e nao a
        # forma: o pg8000 devolve cada linha como **lista** e nao como tuplo, e
        # a primeira versao deste teste esperava `[(False,)]`.
        self.assertEqual(len(linhas), 1, "a vista devia dar uma linha")
        self.assertEqual(linhas[0][0], False, "e devia ser a ultima")

    def test_a_vista_desempata_duas_provas_do_mesmo_instante(self) -> None:
        """**O defeito que o CI apanhou, e a asserção que o fecha.**

        A primeira versao desta revisao ordenava a vista por
        `(ocorrido_em DESC, id DESC)` e afirmava que um empate no `ocorrido_em`
        era impossivel dentro do trio «porque a `consent_event_prova_uq` o
        impede». **E falso:** a unicidade e sobre o `evidence_hash`, e duas
        provas do mesmo trio com resumos diferentes entram as duas — e podem
        partilhar o instante, porque a hora que a Meta manda tem resolucao de
        **segundos**. Com o empate, a vista desempatava pelo `uuid` aleatorio: o
        ensaio contra a base escolhia a `v2` numa maquina e a `v1` no CI, com os
        mesmos dados.

        Aqui escrevem-se duas provas com o **mesmo** `ocorrido_em` e verifica-se
        que a vista devolve a que foi **escrita depois** — que e o que o
        `registado_em` resolve, e o unico sitio do esquema onde
        `clock_timestamp()` e a omissao.
        """
        instante = "2026-11-02T14:03:11+00:00"
        self.cursor.execute(
            "INSERT INTO platform.consent_event "
            "(tenant_id, contact_id, purpose, text_version, accepted, canal, "
            " evidence_hash, ocorrido_em) "
            "VALUES (%s, %s, 'transacao', 'v1', true, 'whatsapp', %s, %s)",
            (self.tenant, self.contacto, PROVA, instante),
        )
        self.cursor.execute(
            "INSERT INTO platform.consent_event "
            "(tenant_id, contact_id, purpose, text_version, accepted, canal, "
            " evidence_hash, ocorrido_em) "
            "VALUES (%s, %s, 'transacao', 'v2', true, 'whatsapp', %s, %s)",
            (self.tenant, self.contacto, bytes([153]) + PROVA[1:], instante),
        )
        # As duas partilham o instante: e isso que faz deste teste uma prova do
        # desempate e nao do `ocorrido_em`.
        self.cursor.execute(
            "SELECT count(DISTINCT ocorrido_em) FROM platform.consent_event "
            "WHERE contact_id = %s",
            (self.contacto,),
        )
        self.assertEqual(self.cursor.fetchone()[0], 1, "o ensaio devia empatar")

        self.cursor.execute(
            "SELECT text_version FROM platform.consent_actual "
            "WHERE contact_id = %s AND purpose = 'transacao'",
            (self.contacto,),
        )
        linhas = self.cursor.fetchall()
        self.assertEqual(len(linhas), 1)
        self.assertEqual(linhas[0][0], "v2", "a vista devia dar a escrita depois")

    def test_a_vista_nao_mostra_a_prova_nem_o_canal(self) -> None:
        """Quem pergunta «aceitou?» precisa da resposta e nao da prova.

        As tres colunas de fora tem cada uma a sua razao, e estao escritas no
        `EXCLUIDAS_DA_VISTA` do `test_inventario.py`. A que importa aqui e o
        `evidence_hash`: quem a precisa le a tabela, que e outro caminho e outro
        privilegio de leitura a pedir no dia em que os papeis se separarem.
        """
        self.cursor.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'platform' AND table_name = 'consent_actual' "
            "ORDER BY column_name"
        )
        self.assertEqual(
            [c for (c,) in self.cursor.fetchall()],
            ["accepted", "contact_id", "ocorrido_em", "purpose", "tenant_id",
             "text_version"],
        )

    # --------------------------------------------------------- o texto do aviso

    def test_o_texto_nasce_vazio_e_e_de_plataforma(self) -> None:
        """A tabela nasce **sem linhas**, e nao tem `tenant_id`.

        O texto e juridico e esta «a confirmar por parecer» (KAM-104): uma
        migracao que o escrevesse punha no esquema uma afirmacao legal que
        ninguem reviu. E nao e dado de tenant — e um texto revisto uma vez e
        mostrado por todas as lojas —, pelo que nao entra no X-05: o gate 6
        pergunta por RLS as tabelas que **tem** a coluna.
        """
        self.cursor.execute("SELECT count(*) FROM platform.consent_texts")
        self.assertEqual(self.cursor.fetchone()[0], 0)
        self.cursor.execute(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_schema = 'platform' AND table_name = 'consent_texts' "
            "AND column_name = 'tenant_id'"
        )
        self.assertEqual(self.cursor.fetchone()[0], 0)

    def test_um_texto_vazio_e_recusado(self) -> None:
        """Um aviso vazio e pior do que nenhum: ele e a prova de que se informou."""
        with self.assertRaises(Exception) as capturado:
            self.cursor.execute(
                "INSERT INTO platform.consent_texts "
                "(version, purpose, texto, hash, vigente_desde) "
                "VALUES ('v1', 'transacao', '  ', %s, now())",
                (PROVA,),
            )
        self.assertEqual(sqlstate(capturado.exception), CHECK_VIOLATION)

    def test_a_chave_do_texto_e_a_versao_e_a_finalidade(self) -> None:
        """Duas finalidades podem ter avisos diferentes na mesma versao."""
        for finalidade in ("transacao", "marketing"):
            self.cursor.execute(
                "INSERT INTO platform.consent_texts "
                "(version, purpose, texto, hash, vigente_desde) "
                "VALUES ('v1', %s, 'Aviso de ensaio', %s, now())",
                (finalidade, PROVA),
            )
        with self.assertRaises(Exception) as capturado:
            self.cursor.execute(
                "INSERT INTO platform.consent_texts "
                "(version, purpose, texto, hash, vigente_desde) "
                "VALUES ('v1', 'transacao', 'Outro', %s, now())",
                (PROVA,),
            )
        self.assertEqual(sqlstate(capturado.exception), UNIQUE_VIOLATION)


class TestAppendOnly(ComBase):
    """O *append-only* do criterio 6, pelo **privilegio** e nao pela politica.

    Nao se afirma que o modulo nao corrige uma linha — afirma-se que nenhum
    codigo que corra como `kamba_app` o pode fazer. Com a metade positiva
    primeiro, pela regra do `../docs/isolamento.md`: sem ela, uma concessao em
    falta por inteiro passava as negativas.
    """

    def setUp(self) -> None:
        super().setUp()
        self.admin = self.ligar("admin").cursor()
        self.tenant = factories.tenant(self.admin)
        self.contacto = factories.contacto(self.admin, self.tenant)
        self.admin.execute(
            "INSERT INTO platform.consent_event "
            "(tenant_id, contact_id, purpose, text_version, accepted, canal, "
            " evidence_hash) "
            "VALUES (%s, %s, 'transacao', 'v1', true, 'whatsapp', %s)",
            (self.tenant, self.contacto, PROVA),
        )
        self.admin.execute(
            "INSERT INTO platform.consent_texts "
            "(version, purpose, texto, hash, vigente_desde) "
            "VALUES ('v1', 'transacao', 'Aviso de ensaio', %s, now())",
            (PROVA,),
        )
        self.app = self.ligar("app").cursor()
        self.app.execute("SELECT set_config('app.tenant_id', %s, true)", (self.tenant,))

    def test_a_app_le_as_duas_e_a_vista(self) -> None:
        """A metade positiva, e e o **privilegio** e nao a linha.

        **Nao se contam linhas aqui, e a razao e o ensaio e nao a tabela:** a
        ligacao que o `ComBase` da nunca confirma, pelo que a sessao da
        aplicacao — que e outra — nao ve o que o administrador acabou de
        escrever. A primeira versao deste teste contava `1` e media `0`.
        O que o criterio 6 pede e que o `SELECT` **exista**, e um `count(*)` que
        corra sem `42501` prova-o; quem prova que a linha certa aparece a quem
        a pode ver e o X-03 do gate 6 e o ensaio em Node.
        """
        for relacao in ("consent_event", "consent_texts", "consent_actual"):
            with self.subTest(relacao=relacao):
                self.app.execute(f"SELECT count(*) FROM platform.{relacao}")
                self.assertIsNotNone(self.app.fetchone())

    def test_a_app_tem_insert_na_prova_e_nao_no_texto(self) -> None:
        """A outra metade positiva, e tambem pelo **privilegio**.

        **Nao se tenta o `INSERT` a serio, e a razao e a mesma do teste
        anterior:** a ligacao do `ComBase` nunca confirma, pelo que o contacto
        que o administrador acabou de criar nao existe para a sessao da
        aplicacao — e a FK composta recusa com `23503` antes de o privilegio
        chegar a ser avaliado. A primeira versao deste teste tentou-o e mediu
        exactamente isso.

        O que se afirma e a assimetria que o criterio 6 desenha: `INSERT` na
        prova **sim**, `INSERT` no texto do aviso **nao**. Quem o exercita a
        escrever de verdade e o ensaio em Node, contra dados confirmados.
        """
        for relacao, esperado in (("consent_event", True), ("consent_texts", False)):
            with self.subTest(relacao=relacao):
                self.app.execute(
                    "SELECT has_table_privilege('kamba_app', %s, 'INSERT')",
                    (f"platform.{relacao}",),
                )
                self.assertEqual(self.app.fetchone()[0], esperado)

    def test_a_app_nao_altera_a_prova(self) -> None:
        with self.assertRaises(Exception) as capturado:
            self.app.execute(
                "UPDATE platform.consent_event SET accepted = false WHERE tenant_id = %s",
                (self.tenant,),
            )
        self.assertEqual(sqlstate(capturado.exception), PRIVILEGIO_INSUFICIENTE)

    def test_a_app_nao_apaga_a_prova(self) -> None:
        with self.assertRaises(Exception) as capturado:
            self.app.execute(
                "DELETE FROM platform.consent_event WHERE tenant_id = %s",
                (self.tenant,),
            )
        self.assertEqual(sqlstate(capturado.exception), PRIVILEGIO_INSUFICIENTE)

    def test_a_app_nao_escreve_o_texto_do_aviso(self) -> None:
        """Dar `INSERT` aqui deixava o caminho que serve clientes publicar um
        texto juridico. Quem publica uma versao e operacao."""
        for instrucao, parametros in (
            (
                "INSERT INTO platform.consent_texts "
                "(version, purpose, texto, hash, vigente_desde) "
                "VALUES ('v9', 'transacao', 'Inventado', %s, now())",
                (PROVA,),
            ),
            ("UPDATE platform.consent_texts SET texto = 'Outro'", ()),
            ("DELETE FROM platform.consent_texts", ()),
        ):
            with self.subTest(instrucao=instrucao.split()[0]):
                with self.assertRaises(Exception) as capturado:
                    self.app.execute(instrucao, parametros)
                self.assertEqual(
                    sqlstate(capturado.exception), PRIVILEGIO_INSUFICIENTE
                )
                self.app.connection.rollback()
                self.app.execute(
                    "SELECT set_config('app.tenant_id', %s, true)", (self.tenant,)
                )

    def test_a_vista_respeita_a_rls_de_quem_a_consulta(self) -> None:
        """**O que o `security_invoker` compra, medido.**

        Com o contexto de outro *tenant*, a vista nao mostra a linha deste. Sem
        a opcao, a vista corria como o dono e a RLS passava a depender do
        `FORCE` — e uma vista e exactamente o sitio onde ninguem iria procurar.
        """
        outro = factories.tenant(self.admin)
        self.app.connection.rollback()
        self.app.execute("SELECT set_config('app.tenant_id', %s, true)", (outro,))
        self.app.execute(
            "SELECT count(*) FROM platform.consent_actual WHERE tenant_id = %s",
            (self.tenant,),
        )
        self.assertEqual(self.app.fetchone()[0], 0)


class TestDowngradeDa0015(unittest.TestCase):
    """Desce com linhas e sobe outra vez, e **nao recusa**.

    A razao esta na revisao: o que se perde e prova de consentimento, e e por
    isso que a guarda com copia para ficheiro — o que a `0010` e a `0012` fazem
    — **nao** e o mecanismo certo. Guardar prova juridica num JSON fora do
    esquema, sem RLS e sem retencao, era trocar um problema por outro pior.
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
                    "DELETE FROM platform.consent_event WHERE tenant_id = %s",
                    (tenant,),
                )
                self.cursor.execute(
                    "DELETE FROM platform.contacts WHERE tenant_id = %s", (tenant,)
                )
                self.cursor.execute(
                    "DELETE FROM platform.tenants WHERE id = %s", (tenant,)
                )
            self.cursor.execute("DELETE FROM platform.consent_texts")
        finally:
            self.conexao.close()

    def test_desce_com_linhas_e_sobe_outra_vez(self) -> None:
        tenant = factories.tenant(self.cursor)
        self.tenants.append(tenant)
        contacto = factories.contacto(self.cursor, tenant)
        self.cursor.execute(
            "INSERT INTO platform.consent_event "
            "(tenant_id, contact_id, purpose, text_version, accepted, canal, "
            " evidence_hash) "
            "VALUES (%s, %s, 'transacao', 'v1', true, 'whatsapp', %s)",
            (tenant, contacto, PROVA),
        )
        self.assertEqual(_tabelas(self.cursor), TABELAS)
        self.assertEqual(_vistas(self.cursor), VISTAS)

        alembic_ok("downgrade", "0014")
        # As duas tabelas **e a vista** desapareceram, e o contacto ficou.
        self.assertEqual(_tabelas(self.cursor), TABELAS_ATE_0014)
        self.assertEqual(_vistas(self.cursor), ())
        self.cursor.execute(
            "SELECT count(*) FROM platform.contacts WHERE contact_id = %s", (contacto,)
        )
        self.assertEqual(self.cursor.fetchone()[0], 1)

        alembic_ok("upgrade", "head")
        self.assertEqual(_tabelas(self.cursor), TABELAS)
        self.assertEqual(_vistas(self.cursor), VISTAS)
        # E a prova nao voltou: a tabela e nova.
        self.cursor.execute(
            "SELECT count(*) FROM platform.consent_event WHERE tenant_id = %s",
            (tenant,),
        )
        self.assertEqual(self.cursor.fetchone()[0], 0)


class TestParidadeDoDominio(unittest.TestCase):
    """O dominio das dez finalidades esta em tres sitios, e os tres dizem o mesmo.

    A revisao, o modulo em TypeScript e o dicionario. Compara-se como **texto**,
    que e a unica coisa que um teste em Python pode afirmar sobre uma constante
    de TypeScript — a forma do `TestTarifas` do `tests_outbound` e do
    `TestParidadeDosDominios` do KAM-021.

    **O quarto sitio tem gate proprio e nao se repete aqui:** o `enum` dos
    contratos de evento, que o `contract_diff dominios` (gate 7) confronta com o
    canon nos dois sentidos desde o KAM-159.
    """

    @classmethod
    def setUpClass(cls) -> None:
        raiz = pathlib.Path(__file__).resolve().parents[2]
        cls.revisao = (
            raiz / "db" / "migrations" / "versions" / "0015_consentimento.py"
        ).read_text(encoding="utf-8")
        cls.ts = (
            raiz / "packages" / "core-ts" / "src" / "consentimento" / "contrato.ts"
        ).read_text(encoding="utf-8")

    def _da_revisao(self) -> list[str]:
        achado = re.search(r"^FINALIDADES = \(([^)]*)\)", self.revisao, re.M | re.S)
        self.assertIsNotNone(achado, "FINALIDADES nao esta na revisao 0015")
        assert achado is not None
        return [
            parte.strip().strip(",").strip().strip("\"").strip("'")
            for parte in achado.group(1).replace("\n", " ").split(",")
            if parte.strip()
        ]

    def test_a_revisao_declara_as_dez(self) -> None:
        self.assertEqual(self._da_revisao(), list(FINALIDADES))

    def test_o_modulo_declara_exactamente_as_mesmas(self) -> None:
        """Bloco inteiro e nao valor a valor: uma lista que **cresca** de um lado
        so e tao divergente como uma que encolha."""
        bloco = "export const FINALIDADES = [\n" + "".join(
            f'  "{f}",\n' for f in self._da_revisao()
        )
        self.assertIn(
            bloco,
            self.ts,
            "o FINALIDADES do modulo nao e exactamente o dominio do "
            "consent_event_purpose_ck",
        )


if __name__ == "__main__":
    unittest.main()
