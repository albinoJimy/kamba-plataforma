"""X-05 — catalogo: toda a tabela com coluna de tenant tem RLS `FORCE` e politica.

Criterios de aceitacao 1 e 6 do KAM-004, e a regressao que os Testes Requeridos
pedem: «uma migracao de teste que cria tabela com `tenant_id` sem RLS deve
fazer X-05 falhar».
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import ligacao
from tests.base import ComBase
from tests_isolamento import catalogo, sementes


class TestCatalogoReal(ComBase):
    """O schema tal como as migracoes o deixam."""

    def setUp(self) -> None:
        super().setUp()
        self.cursor = self.ligar("admin").cursor()

    def test_x05_todas_as_tabelas_isoladas_tem_rls_force_e_politica(self) -> None:
        self.assertEqual(
            catalogo.verificar_rls(self.cursor, catalogo.excepcoes_rls()), []
        )

    def test_a_unica_excepcao_de_rls_e_a_cabeca_da_cadeia(self) -> None:
        """O criterio dizia «inicialmente vazia»; deixou de estar, e com razao.

        `platform.audit_heads` (KAM-012) tem `tenant_id` e nao tem RLS. Quem
        lhe escreve e um trigger `SECURITY DEFINER` que corre como o dono, e
        com `FORCE` o dono tambem esta sujeito a politica — a cadeia das
        accoes de plataforma, de `tenant_id` nulo, ficava invisivel e essas
        accoes eram impossiveis de registar. A tabela nao guarda facto nenhum
        de negocio: uma linha por cadeia, com um hash opaco.

        Este teste muda **a ver**, que e o que o criterio pede: a lista nao
        cresce sem alguem reescrever esta afirmacao.
        """
        self.assertEqual(set(catalogo.excepcoes_rls()), {"platform.audit_heads"})

    def test_a_descoberta_encontra_as_tabelas_todas(self) -> None:
        """Se a descoberta encolher, a suite inteira passa a testar menos.

        **O nome nao leva o numero, e deixou de o levar no KAM-021.** Chamava-se
        `..._as_vinte_e_uma_tabelas` e a assercao ja ia em vinte e tres: o numero
        no nome ficou para tras duas vezes — no KAM-020 e aqui — porque quem
        acrescenta uma tabela mexe na lista e nao no nome do metodo, e um nome que
        diz um numero errado e pior do que um que nao diz nenhum. O numero que
        conta esta na lista abaixo, que e o que falha.

        Catorze com o KAM-012, que trouxe o `audit_log` e o `audit_heads`. O
        segundo **nao tem** RLS — a descoberta lista o que **devia** te-la, e
        e a lista de `ci/rls_exceptions.yaml` que o dispensa, com o ADR. Uma
        tabela que saia daqui sai de X-03, X-04 e X-05 ao mesmo tempo.

        Dezasseis desde o KAM-009: o contador de uso e o livro de
        idempotencia. A ordem e a do `sorted()` do Python, que compara por
        ponto de codigo — e por isso `tenant_usage` vem **antes** de
        `tenants` (`_` e 0x5F, `s` e 0x73), ao contrario do que uma
        ordenacao en_US daria.

        Dezassete desde o KAM-014: a `conversations`. E a **primeira** tabela
        do caminho do webhook a entrar aqui — as duas da `0008` nao tem
        `tenant_id`, porque o tenant so nasce no CHR, que corre depois delas.

        Dezanove desde o KAM-015: a `message_templates` e a `outbound_messages`.
        Nao ha entrada em `ci/rls_exceptions.yaml` para nenhuma das duas — tem
        `tenant_id`, logo levam RLS `FORCE` e a politica `tenant_iso`, e e a
        coluna que as faz entrar aqui sozinhas.

        Vinte e duas desde o KAM-020: a `media_assets`. Tem tres FK (`tenants`, e
        `contacts` e `conversations` as duas compostas com o `tenant_id` — nao e a
        que tem mais: a `outbound_messages` tem quatro), e entra aqui pela coluna como todas as
        outras — a chave primaria dela e o `asset_id`, que **nao** leva
        `tenant_id`, pelo que leva indice proprio `(tenant_id, criado_at DESC)`
        pela mesma razao da `handoffs`.

        Vinte e tres desde o KAM-021: a `channel_quality_log`. Tem duas FK (a do
        `tenants` e a composta para `tenant_channels`), chave primaria `id` que
        **nao** leva `tenant_id` — logo indice proprio `(tenant_id,
        ocorrido_em DESC)`, pela razao da `handoffs` e da `media_assets` — e e a
        **primeira** desta lista a que `kamba_app` nao tem `UPDATE`: um registo
        de transicoes nao se corrige, e por isso a receita de sementes nao tem
        coluna alteravel e o que se prova e que o privilegio nem existe.

        Vinte e quatro desde o KAM-022: a `consent_event`. A `consent_texts`
        **nao** entra, e nao e esquecimento: nao tem `tenant_id`, porque um aviso
        de privacidade e um texto juridico de plataforma.

        Vinte e cinco desde o KAM-016: a `channel_onboarding`. Tem duas FK (a do
        `tenants` e a composta para `tenant_channels`) e chave primaria `id` que
        **nao** leva `tenant_id` — logo indice proprio `(tenant_id, fase)`, pela
        razao da `handoffs`, da `media_assets` e da `channel_quality_log`. E a
        **primeira** desta lista em que `kamba_app` **le e nao escreve nada**: a
        `channel_quality_log` le e insere, a `events_dlq` insere e nao le, esta
        so le. A razao e que o onboarding de um canal e provisionamento, e quem
        provisiona e o `kamba_batch` (dicionario §3.2) — pelo que a receita de
        sementes tem `escrita_do_papel=False` e `coluna_alteravel=None`, e o que
        se prova e que os privilegios de escrita nem existem.

        Vinte e seis desde o KAM-017: a `channel_coexistence`. Tem as mesmas
        duas FK e a mesma chave primaria `id` sem `tenant_id` — logo indice
        proprio `(tenant_id, estado)`. Ao contrario da `channel_onboarding`,
        `kamba_app` **escreve** nesta: a coexistencia corre no caminho de um
        *webhook* e nao de retaguarda, pelo que a receita de sementes tem coluna
        alteravel (`estado`). O `kamba_batch` tem `SELECT` e `DELETE` e **nao**
        `INSERT`, de proposito — nao ha caminho de retaguarda que abra uma
        sincronizacao —, e por isso a receita semeia o administrador.

        **O nome deste teste diz «vinte e uma» e a lista tem vinte e seis.** O
        KAM-020 deixou-o a dizer vinte e uma ao fazer vinte e duas, e quatro
        tickets passaram por aqui depois sem o renomear; nao se renomeia agora,
        pela mesma razao — renomear o teste de outro ticket a meio deste e ruido
        no diff. Fica em `docs/dividas-documentais.md`.

        Vinte e oito desde o KAM-115: a `owner_contacts` e a `owner_notices`. Sao
        as duas primeiras tabelas isoladas que **nao tocam em `tenant_channels`**
        — tem uma FK so, para `tenants` —, e a razao e o que o ticket e: o aviso
        e do **dono** e nao do canal, e o canal, quando faz parte da historia,
        vai dentro do `episodio`, que e texto opaco. As duas tem chave primaria
        `id` sem `tenant_id`, logo indice proprio a comecar por ele. Na
        `owner_notices` o `kamba_batch` **insere**, e e a unica tabela isolada em
        que ele o faz por uma razao de produto e nao de provisionamento: os
        lembretes das 24 h e das 72 h do criterio 4 sao escritas de retaguarda.

        Vinte e uma desde o KAM-019: a `handoff_accounts` e a `handoffs`. A
        segunda e a **primeira tabela desta lista cuja chave primaria nao leva
        `tenant_id`** — e o `handoff_id` derivado —, e por isso levou um indice
        proprio `(tenant_id, opened_at DESC)` para cumprir a convencao que o
        `test_tenant_id_e_not_null_e_vem_primeiro_num_indice` impoe. Na
        descoberta isso nao se ve: aqui entra pela coluna, como as outras.
        """
        self.assertEqual(
            catalogo.tabelas_isoladas(self.cursor),
            [
                # KAM-012. Nenhuma das duas tem receita de sementes, e as
                # duas razoes estao em `sementes.SEM_RECEITA_COM_RAZAO`: o
                # `audit_heads` nao tem politica para provar, e o `audit_log` e
                # append-only — semea-lo obrigava a desligar o trigger na
                # limpeza.
                ("platform", "audit_heads", "tenant_id"),
                ("platform", "audit_log", "tenant_id"),
                # KAM-021: o registo das transicoes de qualidade. A posicao
                # e **depois** das duas `audit_*` e **antes** das
                # `contact_*`: no `sorted()` por ponto de codigo, «ch»
                # vence «co» porque 'h' < 'o', e perde contra «au».
                # KAM-017: o estado de coexistencia. A posicao e **antes** da
                # `channel_onboarding`: no `sorted()` por ponto de codigo,
                # «channel_c» vence «channel_o» porque 'c' < 'o'.
                ("platform", "channel_coexistence", "tenant_id"),
                # KAM-016: a tentativa de onboarding. A posicao e **antes** da
                # `channel_quality_log`: no `sorted()` por ponto de codigo,
                # «channel_o» vence «channel_q» porque 'o' < 'q'.
                ("platform", "channel_onboarding", "tenant_id"),
                ("platform", "channel_quality_log", "tenant_id"),
                # KAM-022: a prova de consentimento. A `consent_texts`
                # **nao** esta aqui e nao e esquecimento: nao tem
                # `tenant_id`, porque um aviso de privacidade e um texto
                # juridico de plataforma e nao dado de tenant — e a
                # descoberta pergunta pela coluna. No `sorted()`,
                # «consent_event» vem depois de «channel_quality_log»
                # («ch» < «co») e antes de «contact_deks» («consent_» <
                # «contact_», porque 's' < 't').
                ("platform", "consent_event", "tenant_id"),
                ("platform", "contact_deks", "tenant_id"),
                ("platform", "contact_endpoints", "tenant_id"),
                ("platform", "contacts", "tenant_id"),
                # KAM-014: a conversa.
                ("platform", "conversations", "tenant_id"),
                ("platform", "entitlements", "tenant_id"),
                # KAM-006: as tres do consumo. A `evt_dlq_aprovacoes` **nao**
                # esta aqui, e nao e esquecimento: nao tem `tenant_id`, porque
                # o isolamento do que se aprova vem da linha da DLQ que ela
                # referencia.
                ("platform", "events_consumed", "tenant_id"),
                ("platform", "events_dlq", "tenant_id"),
                ("platform", "events_log", "tenant_id"),
                ("platform", "events_outbox", "tenant_id"),
                ("platform", "evt_acoes", "tenant_id"),
                ("platform", "evt_agregado_seq", "tenant_id"),
                # KAM-019: as duas do handoff, e a posicao nao e indiferente —
                # `handoff*` vem **depois** de `evt_*` («e» < «h») e antes de
                # `message_templates`. Entre as duas, `handoff_accounts` vem
                # primeiro (`_` e 0x5F, `s` e 0x73), a mesma armadilha do
                # `tenant_usage`/`tenants` desta lista. A primeira versao pos
                # as duas depois de `entitlements` e o teste recusou.
                ("platform", "handoff_accounts", "tenant_id"),
                ("platform", "handoffs", "tenant_id"),
                # KAM-020: a midia, e a posicao e entre `handoffs` e
                # `message_templates` — «ha» < «me», e contra
                # `message_templates` decide o terceiro caracter («d» < «s»).
                ("platform", "media_assets", "tenant_id"),
                # KAM-015: as duas da saida de canal. A ordem e a do
                # `sorted()`, que compara por ponto de codigo.
                ("platform", "message_templates", "tenant_id"),
                ("platform", "outbound_messages", "tenant_id"),
                # KAM-115: as duas do aviso ao dono, e a posicao e **depois**
                # de `outbound_messages`: no `sorted()` por ponto de codigo,
                # «ou» vence «ow» porque 'u' (0x75) < 'w' (0x77). Entre as duas,
                # «owner_c» vem antes de «owner_n». As duas tem uma FK so — para
                # `tenants` — e chave primaria `id` sem `tenant_id`, logo indice
                # proprio a comecar por ele.
                ("platform", "owner_contacts", "tenant_id"),
                ("platform", "owner_notices", "tenant_id"),
                ("platform", "tenant_channels", "tenant_id"),
                # KAM-009: o contador de uso e o livro de idempotencia.
                ("platform", "tenant_usage", "tenant_id"),
                ("platform", "tenants", "id"),
                # KAM-028: o registo das invocacoes da ToolLayer. Sem receita de
                # sementes, e a razao esta em `sementes.SEM_RECEITA_COM_RAZAO`:
                # e *append-only* por um *trigger* `ENABLE ALWAYS`, e estas
                # receitas limpam com `DELETE`. Aqui entra pela coluna, como as
                # outras — o que a descoberta ve e o `tenant_id` e a politica.
                ("platform", "tool_audit", "tenant_id"),
                ("platform", "usage_ledger", "tenant_id"),
            ],
        )

    def test_a_particao_do_arquivo_nao_entra_na_descoberta(self) -> None:
        """E tem de ser encontrada **como particao**, ou nao se verificava nada.

        A `events_log_default` tem `tenant_id` e entrava na descoberta sozinha,
        com ela a receita de sementes e os canarios — sobre a mesma linha que o
        pai ja semeia. Fica de fora da descoberta e dentro de
        `particoes_de_isoladas`, que e o que `verificar_particoes` percorre.
        """
        descobertas = {t for _, t, _ in catalogo.tabelas_isoladas(self.cursor)}
        self.assertNotIn("events_log_default", descobertas)
        self.assertEqual(
            catalogo.particoes_de_isoladas(self.cursor),
            [("platform", "events_log_default", "events_log")],
        )

    def test_cada_particao_tem_a_sua_rls_e_nenhum_privilegio(self) -> None:
        """X-05, segunda parte (KAM-005): a politica do pai nao cobre a particao."""
        self.assertEqual(catalogo.verificar_particoes(self.cursor), [])

    def test_cada_tabela_isolada_tem_receita_de_sementes(self) -> None:
        """Uma tabela que a suite nao sabe semear e uma tabela que nao testa."""
        descobertas = {(s, t) for s, t, _ in catalogo.tabelas_isoladas(self.cursor)}
        self.assertEqual(
            descobertas - sementes.SEM_RECEITA_COM_RAZAO, set(sementes.RECEITAS)
        )
        self.assertEqual(set(sementes.ORDEM), set(sementes.RECEITAS))
        # E o que esta declarado sem receita tem mesmo de existir: uma entrada
        # em `SEM_RECEITA_COM_RAZAO` que nao corresponda a tabela nenhuma e uma
        # porta aberta com a chave perdida.
        todas = {
            (esquema, tabela)
            for esquema, tabela in self.consultar(
                "SELECT schemaname::text, tablename::text FROM pg_tables "
                " WHERE schemaname = 'platform'"
            )
        }
        self.assertLessEqual(sementes.SEM_RECEITA_COM_RAZAO, todas)

    def test_as_politicas_sao_exactamente_as_declaradas(self) -> None:
        """Politicas permissivas somam-se por OU: uma a mais abre o que a `tenant_iso` fecha.

        O teste abaixo so olha para a `tenant_iso`. Uma `CREATE POLICY ... FOR
        SELECT TO kamba_app USING (true)` em `contacts` deixava-a intacta e
        punha a aplicacao a ler os contactos de todos os tenants (revisao
        adversarial do KAM-008). Lista fechada: quem acrescentar uma politica
        escreve-a aqui, com o papel a que se aplica.
        """
        linhas = self.consultar(
            "SELECT tablename::text, policyname::text, cmd::text, roles::text "
            "FROM pg_policies ORDER BY 1, 2"
        )
        self.assertEqual(
            linhas,
            [
                # KAM-012: o `audit_heads` nao aparece — nao tem politica, por
                # excepcao declarada.
                ("audit_log", "tenant_iso", "ALL", "{public}"),
                # KAM-017: o estado de coexistencia, antes da de onboarding
                # («channel_c» < «channel_o»).
                ("channel_coexistence", "tenant_iso", "ALL", "{public}"),
                # KAM-016: a tentativa de onboarding, antes da de qualidade
                # («channel_o» < «channel_q»).
                ("channel_onboarding", "tenant_iso", "ALL", "{public}"),
                # KAM-021: o registo das transicoes de qualidade.
                ("channel_quality_log", "tenant_iso", "ALL", "{public}"),
                # KAM-022: a prova de consentimento.
                ("consent_event", "tenant_iso", "ALL", "{public}"),
                ("contact_deks", "tenant_iso", "ALL", "{public}"),
                ("contact_endpoints", "tenant_iso", "ALL", "{public}"),
                ("contacts", "tenant_iso", "ALL", "{public}"),
                # KAM-014: a primeira tabela do caminho do webhook com
                # `tenant_id`, e por isso a primeira com politica.
                ("conversations", "tenant_iso", "ALL", "{public}"),
                ("entitlements", "tenant_iso", "ALL", "{public}"),
                ("events_consumed", "tenant_iso", "ALL", "{public}"),
                ("events_dlq", "tenant_iso", "ALL", "{public}"),
                ("events_log", "tenant_iso", "ALL", "{public}"),
                ("events_log_default", "tenant_iso", "ALL", "{public}"),
                ("events_outbox", "tenant_iso", "ALL", "{public}"),
                ("evt_acoes", "tenant_iso", "ALL", "{public}"),
                ("evt_agregado_seq", "tenant_iso", "ALL", "{public}"),
                # KAM-019: as duas do handoff, pela ordem da coleccao `C`.
                ("handoff_accounts", "tenant_iso", "ALL", "{public}"),
                ("handoffs", "tenant_iso", "ALL", "{public}"),
                # KAM-020: a midia, pela mesma ordem.
                ("media_assets", "tenant_iso", "ALL", "{public}"),
                # KAM-015: as duas da saida de canal.
                ("message_templates", "tenant_iso", "ALL", "{public}"),
                ("outbound_messages", "tenant_iso", "ALL", "{public}"),
                # KAM-115: as duas do aviso ao dono, depois de
                # `outbound_messages` («ou» < «ow»).
                ("owner_contacts", "tenant_iso", "ALL", "{public}"),
                ("owner_notices", "tenant_iso", "ALL", "{public}"),
                ("tenant_channels", "resolver_leitura", "SELECT", "{kamba_resolver}"),
                ("tenant_channels", "tenant_iso", "ALL", "{public}"),
                # KAM-009. A ordem e a da coleccao `C` e nao a da base: o
                # `pg_policies.tablename` e do tipo `name`, que tem colacao
                # `C`, e o `::text` do `SELECT` herda-a. Por isso
                # `tenant_usage` vem antes de `tenants`, ao contrario do que
                # a colacao `en_US.utf8` da base daria.
                ("tenant_usage", "tenant_iso", "ALL", "{public}"),
                ("tenants", "resolver_leitura", "SELECT", "{kamba_resolver}"),
                ("tenants", "tenant_iso", "ALL", "{public}"),
                # KAM-028: a `tool_audit`. A politica nao e redundante com o
                # *append-only* — o `WITH CHECK` e o que impede o papel da
                # aplicacao de escrever uma linha de auditoria **no nome de
                # outro tenant**, que e o unico tipo de escrita que a tabela
                # aceita.
                ("tool_audit", "tenant_iso", "ALL", "{public}"),
                ("usage_ledger", "tenant_iso", "ALL", "{public}"),
            ],
        )

    def test_a_politica_e_a_tenant_iso_com_using_e_with_check(self) -> None:
        linhas = self.consultar(
            "SELECT tablename, cmd, permissive, roles::text, qual, with_check "
            "FROM pg_policies WHERE schemaname = 'platform' AND policyname = 'tenant_iso' "
            "ORDER BY 1"
        )
        self.assertEqual(
            [l[0] for l in linhas],
            [# KAM-012: o registo de auditoria. O `audit_heads` nao esta
             # aqui, por excepcao declarada em `ci/rls_exceptions.yaml`.
             "audit_log",
             # KAM-017: o estado de coexistencia. **Quinta e sexta listas
             # deste ficheiro a precisarem da tabela nova** (esta e a de
             # `test_as_politicas_sao_exactamente_as_declaradas`), e a licao
             # repete-se: o KAM-016 escreveu que as tres primeiras ja estavam
             # feitas quando a quarta falhou, e aqui foram as quatro primeiras
             # que passaram antes de estas duas caírem. Quem acrescentar uma
             # tabela isolada corre o *gate* 6 **inteiro** e nao so o X-03.
             "channel_coexistence",
             # KAM-016: a tentativa de onboarding. **Quarta lista deste
             # ficheiro a precisar dela**, e a licao e a mesma que o KAM-019
             # escreveu: as tres primeiras ja estavam feitas quando esta falhou.
             "channel_onboarding",
             # KAM-021: o registo das transicoes de qualidade.
             "channel_quality_log",
             # KAM-022: a prova de consentimento.
             "consent_event",
             "contact_deks", "contact_endpoints", "contacts",
             # KAM-014: a conversa.
             "conversations", "entitlements",
             # KAM-006: as tres do consumo com `tenant_id`.
             "events_consumed", "events_dlq",
             "events_log", "events_log_default", "events_outbox",
             "evt_acoes", "evt_agregado_seq",
             # KAM-019: as duas do handoff. **Terceira lista deste ficheiro a
             # precisar delas**, e as outras duas ja estavam feitas quando esta
             # falhou — a descoberta, as politicas por nome, e esta, que confere
             # o `USING` e o `WITH CHECK` de cada uma.
             "handoff_accounts", "handoffs",
             # KAM-020: a midia. **Quarta lista deste ficheiro a precisar de
             # uma tabela nova**, e a nota do KAM-019 ja avisava que eram tres:
             # a descoberta, as politicas por nome, e esta. Conta-se aqui para
             # que o proximo nao as descubra uma a uma.
             "media_assets",
             # KAM-015: as duas da saida de canal.
             "message_templates", "outbound_messages",
             # KAM-115: as duas do aviso ao dono. **Quarta lista deste ficheiro
             # a precisar delas**, e as outras tres ja estavam feitas quando esta
             # falhou — exactamente como o KAM-017 avisou duas notas acima. A
             # licao nao e sobre este ticket: quem acrescentar uma tabela isolada
             # corre o *gate* 6 **inteiro**, porque as quatro listas sao quatro
             # perguntas diferentes sobre a mesma tabela.
             "owner_contacts", "owner_notices",
             "tenant_channels",
             # KAM-009: o contador e o livro. `tenant_usage` antes de
             # `tenants` pela colacao `C` do tipo `name` (ver o teste acima).
             "tenant_usage", "tenants",
             # KAM-028: a `tool_audit`, entre `tenants` e `usage_ledger`.
             "tool_audit", "usage_ledger"],
        )
        for tabela, comando, permissiva, papeis, qual, com_check in linhas:
            with self.subTest(tabela=tabela):
                self.assertEqual((comando, permissiva, papeis), ("ALL", "PERMISSIVE", "{public}"))
                coluna = "id" if tabela == "tenants" else "tenant_id"
                for predicado in (qual, com_check):
                    self.assertIn(coluna, predicado)
                    self.assertIn("app.tenant_id", predicado)
                    self.assertIn("NULLIF", predicado.upper())

    def test_nao_ha_security_definer_fora_da_lista(self) -> None:
        self.assertEqual(
            catalogo.verificar_security_definer(
                self.cursor, catalogo.funcoes_permitidas()
            ),
            [],
        )

    def test_nao_ha_vistas_sem_security_invoker(self) -> None:
        self.assertEqual(catalogo.verificar_vistas(self.cursor), [])

    def test_nao_ha_colunas_de_tenant_com_outro_nome(self) -> None:
        self.assertEqual(catalogo.verificar_colunas_de_tenant(self.cursor), [])


class TestRegressao(ComBase):
    """A verificacao sabe dizer «esta mal» — e nomeia o que esta mal.

    Cada teste cria o defeito de proposito, numa transaccao que nunca e
    confirmada: o DDL do PostgreSQL e transaccional, e o `tearDown` desfaz tudo.
    """

    def setUp(self) -> None:
        super().setUp()
        self.conexao = self.ligar("admin")
        self.cursor = self.conexao.cursor()

    def test_tabela_com_tenant_id_sem_rls_faz_x05_falhar(self) -> None:
        self.cursor.execute(
            "CREATE TABLE platform.esquecida (id uuid PRIMARY KEY, tenant_id uuid NOT NULL)"
        )
        problemas = catalogo.verificar_rls(self.cursor, catalogo.excepcoes_rls())
        self.assertEqual(len(problemas), 1, problemas)
        self.assertIn("platform.esquecida", problemas[0])
        self.assertIn("ENABLE ROW LEVEL SECURITY", problemas[0])
        self.assertIn("FORCE ROW LEVEL SECURITY", problemas[0])
        self.assertIn("pelo menos uma politica", problemas[0])

    def test_cada_metade_em_falta_e_nomeada(self) -> None:
        """`ENABLE` sem `FORCE` deixa o dono ver tudo; sem politica ninguem ve nada."""
        self.cursor.execute(
            "CREATE TABLE platform.a_meio (id uuid PRIMARY KEY, tenant_id uuid NOT NULL)"
        )
        self.cursor.execute("ALTER TABLE platform.a_meio ENABLE ROW LEVEL SECURITY")
        problemas = catalogo.verificar_rls(self.cursor, catalogo.excepcoes_rls())
        self.assertEqual(len(problemas), 1, problemas)
        self.assertNotIn("ENABLE ROW LEVEL SECURITY", problemas[0])
        self.assertIn("FORCE ROW LEVEL SECURITY", problemas[0])
        self.assertIn("pelo menos uma politica", problemas[0])

    def test_noutro_schema_aplicacional_tambem_e_apanhada(self) -> None:
        """A descoberta nao e so `platform`: um schema novo entra sozinho."""
        self.cursor.execute("CREATE SCHEMA servicos_ensaio")
        self.cursor.execute(
            "CREATE TABLE servicos_ensaio.marcacoes (id uuid, tenant_id uuid)"
        )
        problemas = catalogo.verificar_rls(self.cursor, catalogo.excepcoes_rls())
        self.assertTrue(any("servicos_ensaio.marcacoes" in p for p in problemas))

    def test_em_public_tambem_e_apanhada(self) -> None:
        """`public` nao e um sitio onde se possa esconder uma tabela de tenant."""
        self.cursor.execute(
            "CREATE TABLE public.encomendas_ensaio (id uuid, tenant_id uuid)"
        )
        problemas = catalogo.verificar_rls(self.cursor, catalogo.excepcoes_rls())
        self.assertEqual(len(problemas), 1, problemas)
        self.assertIn("public.encomendas_ensaio", problemas[0])

    def _particionada_de_ensaio(self) -> None:
        self.cursor.execute(
            "CREATE TABLE platform.eventos_ensaio (tenant_id uuid NOT NULL, n integer) "
            "PARTITION BY RANGE (n)"
        )
        self.cursor.execute(
            "CREATE TABLE platform.eventos_ensaio_1 PARTITION OF platform.eventos_ensaio "
            "FOR VALUES FROM (0) TO (10)"
        )

    def test_tabela_particionada_sem_rls_e_apanhada_pelo_x05(self) -> None:
        """A mae e uma tabela com `tenant_id` como as outras: entra na descoberta.

        A particao **nao** entra — tem a sua verificacao, no teste seguinte. Foi
        esta a mudanca do KAM-005: ate la as duas vinham por `verificar_rls`, e
        com elas vinha a exigencia de uma receita de sementes por particao, que
        nao fecha quando as particoes nascem mensalmente de um *job*.
        """
        self._particionada_de_ensaio()
        problemas = catalogo.verificar_rls(self.cursor, catalogo.excepcoes_rls())
        self.assertEqual(len(problemas), 1, problemas)
        self.assertIn("platform.eventos_ensaio:", problemas[0])

    def test_a_rls_da_mae_nao_chega_a_particao_e_a_verificacao_di_lo(self) -> None:
        """Mediu-se contra o PostgreSQL 18.6: a politica da mae nao cobre a particao.

        Com a mae em `ENABLE`/`FORCE` e com politica, a particao fica com
        `relrowsecurity = false` e zero politicas, e um `SELECT` feito nela
        devolve as linhas de todos os tenants. E por isso que
        `verificar_particoes` existe, e e isto que ela tem de dizer.
        """
        self._particionada_de_ensaio()
        self.cursor.execute(
            "ALTER TABLE platform.eventos_ensaio ENABLE ROW LEVEL SECURITY"
        )
        self.cursor.execute(
            "ALTER TABLE platform.eventos_ensaio FORCE ROW LEVEL SECURITY"
        )
        self.cursor.execute(
            "CREATE POLICY tenant_iso ON platform.eventos_ensaio "
            "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
        )
        # A mae ja esta conforme; a particao continua sem nada.
        self.assertEqual(
            catalogo.verificar_rls(self.cursor, catalogo.excepcoes_rls()), []
        )
        problemas = catalogo.verificar_particoes(self.cursor)
        self.assertEqual(len(problemas), 1, problemas)
        self.assertIn("platform.eventos_ensaio_1", problemas[0])
        self.assertIn("ENABLE ROW LEVEL SECURITY", problemas[0])
        self.assertIn("FORCE ROW LEVEL SECURITY", problemas[0])
        self.assertIn("pelo menos uma politica", problemas[0])

    def test_um_privilegio_concedido_na_particao_e_apanhado(self) -> None:
        """Quem acede, acede pela mae: uma concessao directa abre um caminho sem ela."""
        self._particionada_de_ensaio()
        for alvo in ("platform.eventos_ensaio", "platform.eventos_ensaio_1"):
            self.cursor.execute(f"ALTER TABLE {alvo} ENABLE ROW LEVEL SECURITY")
            self.cursor.execute(f"ALTER TABLE {alvo} FORCE ROW LEVEL SECURITY")
            self.cursor.execute(
                f"CREATE POLICY tenant_iso ON {alvo} USING "
                "(tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
            )
        self.assertEqual(catalogo.verificar_particoes(self.cursor), [])

        self.cursor.execute(
            "GRANT SELECT ON platform.eventos_ensaio_1 TO kamba_app"
        )
        problemas = catalogo.verificar_particoes(self.cursor)
        self.assertEqual(len(problemas), 1, problemas)
        self.assertIn("kamba_app tem privilegio", problemas[0])

    def test_coluna_de_tenant_com_outro_nome_e_apanhada(self) -> None:
        self.cursor.execute(
            "CREATE TABLE platform.nomes_ensaio "
            '(tenant uuid, tenantid uuid, owner_tenant_id uuid, "Tenant_Id" uuid, '
            "tenant_id uuid, inquilino uuid)"
        )
        self.cursor.execute("CREATE TABLE public.nomes_ensaio (id_tenant uuid)")
        problemas = catalogo.verificar_colunas_de_tenant(self.cursor)
        self.assertEqual(len(problemas), 5, problemas)
        for coluna in ("tenant:", "tenantid:", "owner_tenant_id:", "Tenant_Id:"):
            self.assertTrue(
                any(f"platform.nomes_ensaio.{coluna}" in p for p in problemas), coluna
            )
        self.assertTrue(any("public.nomes_ensaio.id_tenant:" in p for p in problemas))

    def test_uma_excepcao_dispensa_a_tabela_e_so_ela(self) -> None:
        self.cursor.execute("CREATE TABLE platform.dispensada (tenant_id uuid)")
        self.cursor.execute("CREATE TABLE platform.nao_dispensada (tenant_id uuid)")
        problemas = catalogo.verificar_rls(
            self.cursor,
            dict(catalogo.excepcoes_rls(),
                 **{"platform.dispensada": {"adr": "ADR-015"}}),
        )
        self.assertEqual(len(problemas), 1, problemas)
        self.assertIn("platform.nao_dispensada", problemas[0])

    def test_excepcao_morta_falha(self) -> None:
        """Uma excepcao para uma tabela que ja tem RLS, ou que nao existe."""
        problemas = catalogo.verificar_rls(
            self.cursor,
            dict(catalogo.excepcoes_rls(),
                 **{
                     "platform.tenant_channels": {"adr": "ADR-015"},
                     "platform.nunca_existiu": {"adr": "ADR-015"},
                 }),
        )
        self.assertEqual(len(problemas), 2, problemas)
        self.assertTrue(all("morta" in p for p in problemas))

    def test_security_definer_e_apanhada(self) -> None:
        self.cursor.execute(
            "CREATE FUNCTION platform.atalho() RETURNS bigint LANGUAGE sql "
            "SECURITY DEFINER AS 'SELECT count(*) FROM platform.tenants'"
        )
        problemas = catalogo.verificar_security_definer(
            self.cursor, catalogo.funcoes_permitidas()
        )
        self.assertEqual(len(problemas), 1, problemas)
        self.assertIn("platform.atalho()", problemas[0])
        self.assertEqual(
            catalogo.verificar_security_definer(
                self.cursor,
                dict(catalogo.funcoes_permitidas(),
                     **{"platform.atalho()": {"adr": "ADR-015"}}),
            ),
            [],
        )

    def test_security_definer_em_public_tambem_e_apanhada(self) -> None:
        """`PUBLIC` tem `EXECUTE` em `public`: era o atalho que ninguem via."""
        self.cursor.execute(
            "CREATE FUNCTION public.atalho_ensaio() RETURNS bigint LANGUAGE sql "
            "SECURITY DEFINER AS 'SELECT count(*) FROM platform.tenants'"
        )
        problemas = catalogo.verificar_security_definer(
            self.cursor, catalogo.funcoes_permitidas()
        )
        self.assertEqual(len(problemas), 1, problemas)
        self.assertIn("public.atalho_ensaio()", problemas[0])

    def test_funcao_invoker_nao_e_apanhada(self) -> None:
        self.cursor.execute(
            "CREATE FUNCTION platform.normal() RETURNS integer LANGUAGE sql AS 'SELECT 1'"
        )
        self.assertEqual(
            catalogo.verificar_security_definer(
                self.cursor, catalogo.funcoes_permitidas()
            ),
            [],
        )

    def test_funcao_permitida_que_nao_existe_falha(self) -> None:
        problemas = catalogo.verificar_security_definer(
            self.cursor,
            dict(catalogo.funcoes_permitidas(),
                 **{"platform.fantasma()": {"adr": "ADR-015"}}),
        )
        self.assertEqual(len(problemas), 1)
        self.assertIn("nao existe", problemas[0])

    def test_vista_sem_security_invoker_e_apanhada_e_com_ele_nao(self) -> None:
        self.cursor.execute(
            "CREATE VIEW platform.v_sem AS SELECT id FROM platform.tenants"
        )
        self.cursor.execute(
            "CREATE VIEW platform.v_com WITH (security_invoker = true) AS "
            "SELECT id FROM platform.tenants"
        )
        problemas = catalogo.verificar_vistas(self.cursor)
        self.assertEqual(len(problemas), 1, problemas)
        self.assertIn("platform.v_sem", problemas[0])

    def test_vista_em_public_tambem_e_apanhada(self) -> None:
        self.cursor.execute(
            "CREATE VIEW public.v_tudo_ensaio AS SELECT * FROM platform.tenants"
        )
        problemas = catalogo.verificar_vistas(self.cursor)
        self.assertEqual(len(problemas), 1, problemas)
        self.assertIn("public.v_tudo_ensaio", problemas[0])

    def test_vista_materializada_e_sempre_apanhada(self) -> None:
        """Nao tem RLS nem `security_invoker`: guarda linhas de todos os tenants."""
        self.cursor.execute(
            "CREATE MATERIALIZED VIEW platform.mv_ensaio AS "
            "SELECT id, tipo FROM platform.tenants"
        )
        problemas = catalogo.verificar_vistas(self.cursor)
        self.assertEqual(len(problemas), 1, problemas)
        self.assertIn("platform.mv_ensaio", problemas[0])


class TestFicheirosDePolitica(unittest.TestCase):
    """`ci/rls_exceptions.yaml` e `ci/secdef_allowlist.yaml`: exigem ADR."""

    def escrever(self, nome: str, corpo: str) -> Path:
        raiz = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (raiz / "ci").mkdir()
        (raiz / "ci" / nome).write_text(corpo, encoding="utf-8", newline="\n")
        return raiz

    ENTRADA = (
        "version: 1\nexcepcoes:\n  - tabela: platform.x\n    adr: {adr}\n"
        "    razao: >-\n      Uma razao com mais de trinta caracteres, para passar a regra.\n"
    )

    def test_excepcao_com_adr_e_aceite(self) -> None:
        for adr in ("ADR-015", "ADR-L003"):
            with self.subTest(adr=adr):
                raiz = self.escrever("rls_exceptions.yaml", self.ENTRADA.format(adr=adr))
                self.assertEqual(list(catalogo.excepcoes_rls(raiz)), ["platform.x"])

    def test_excepcao_sem_adr_valido_e_recusada(self) -> None:
        """Uma aprovacao datada serve para um waiver; aqui nao."""
        for adr in ("aprovacao:fundador@2026-10-11", "KAM-004", "ADR-15", "adr-015"):
            with self.subTest(adr=adr):
                raiz = self.escrever(
                    "rls_exceptions.yaml", self.ENTRADA.format(adr=f'"{adr}"')
                )
                with self.assertRaises(catalogo.PoliticaInvalida):
                    catalogo.excepcoes_rls(raiz)

    def test_campos_em_falta_razao_curta_e_versao_errada(self) -> None:
        casos = {
            "sem adr": "version: 1\nexcepcoes:\n  - tabela: platform.x\n    razao: >-\n      Uma razao com mais de trinta caracteres, para passar.\n",
            "razao curta": "version: 1\nexcepcoes:\n  - tabela: platform.x\n    adr: ADR-015\n    razao: curta\n",
            "versao": "version: 2\nexcepcoes: []\n",
        }
        for nome, corpo in casos.items():
            with self.subTest(caso=nome):
                raiz = self.escrever("rls_exceptions.yaml", corpo)
                with self.assertRaises(catalogo.PoliticaInvalida):
                    catalogo.excepcoes_rls(raiz)

    def test_ficheiro_em_falta_levanta(self) -> None:
        raiz = Path(self.enterContext(tempfile.TemporaryDirectory()))
        with self.assertRaises(catalogo.PoliticaInvalida):
            catalogo.excepcoes_rls(raiz)
        with self.assertRaises(catalogo.PoliticaInvalida):
            catalogo.funcoes_permitidas(raiz)

    def test_os_ficheiros_reais_leem_se_e_tem_o_que_esta_declarado(self) -> None:
        """Os dois nasceram vazios e deixaram de o estar no KAM-012.

        `ci/rls_exceptions.yaml` tem `platform.audit_heads` e
        `ci/secdef_allowlist.yaml` tem `platform.audit_encadear()` — as duas
        pelo mesmo desenho: a cabeca da cadeia de hash e escrita por um trigger
        que corre como o dono, e tem de ser, porque quem escreve a linha de
        auditoria nao pode poder escrever a cabeca.
        """
        self.assertEqual(set(catalogo.excepcoes_rls()), {"platform.audit_heads"})
        self.assertEqual(
            set(catalogo.funcoes_permitidas()), {"platform.audit_encadear()"}
        )


if __name__ == "__main__":
    unittest.main()
