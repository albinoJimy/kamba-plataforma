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
                # KAM-030: a primeira tabela isolada **fora do `platform`**, e
                # por isso a primeira da lista — o `ORDER BY 1, 2` da descoberta
                # ordena por esquema, e «dat» vem antes de «platform». Sem
                # receita de sementes, pela razao do `audit_log`: e append-only e
                # o *trigger* `ENABLE ALWAYS` recusa o `DELETE` da limpeza. O
                # isolamento dela prova-se em `db/tests_agr/test_llm_call_log.py`.
                ("dat", "llm_call_log", "tenant_id"),
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
                # KAM-114: as decisoes do modo concierge.
                ("platform", "draft_decisions", "tenant_id"),
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
                # KAM-043: a oferta, antes de `outbound_messages`
                # («of» < «ou»). E a primeira tabela do esquema em que o
                # `tenant_id` e **parte da chave primaria** e nao uma
                # coluna ao lado dela.
                ("platform", "offer_terms", "tenant_id"),
                # KAM-044: as quatro das encomendas. A ordem e a do `sorted()`
                # por ponto de codigo, e nela o `_` (0x5F) vence o `s` (0x73):
                # as tres `order_*` vem **antes** da `orders_mirror`, e todas
                # depois de `offer_terms` («off» < «ord»).
                #
                # O `order_state_graph` **nao** esta aqui, e nao e falta: nao
                # tem `tenant_id`, e a descoberta do X-05 pergunta pela coluna.
                # E tabela de referencia, como a `evt_subscricoes`.
                ("platform", "order_intents", "tenant_id"),
                ("platform", "order_reconciliation_issues", "tenant_id"),
                ("platform", "order_state_log", "tenant_id"),
                ("platform", "orders_mirror", "tenant_id"),
                ("platform", "outbound_messages", "tenant_id"),
                # KAM-115: as duas do aviso ao dono, e a posicao e **depois**
                # de `outbound_messages`: no `sorted()` por ponto de codigo,
                # «ou» vence «ow» porque 'u' (0x75) < 'w' (0x77). Entre as duas,
                # «owner_c» vem antes de «owner_n». As duas tem uma FK so — para
                # `tenants` — e chave primaria `id` sem `tenant_id`, logo indice
                # proprio a comecar por ele.
                ("platform", "owner_contacts", "tenant_id"),
                ("platform", "owner_notices", "tenant_id"),
                # KAM-052: a conta de pagamento, **depois** das do aviso ao
                # dono e antes de `tenant_channels` ('o' < 'p' < 't'). E a
                # unica desta lista com `tenant_id` **anulavel**, e entra
                # como todas: a descoberta pergunta pela coluna e nao pela
                # nulidade, e o que ela exige — `ENABLE`, `FORCE` e politica
                # — vale igual. Ver o `ANULAVEIS` de
                # `db/tests/test_catalogo.py` para a razao da nulidade.
                ("platform", "payment_accounts", "tenant_id"),
                # KAM-053: a cobranca e o ledger, depois da conta e antes da
                # cotacao — no `sorted()` por ponto de codigo decide o nono
                # caractere, `payment_a` < `payment_c` < `payment_e`.
                #
                # **Duas das quatro tabelas da revisao, e as outras duas ficam
                # de fora sem ninguem as dispensar:** o
                # `payment_callbacks_inbox` nao tem `tenant_id` (quem chega
                # ainda nao o revelou, `docs/tecnica/04` secao 5.1) e a
                # `payment_outbox_map` e configuracao global, como a
                # `evt_subscricoes`. A descoberta pergunta pela **coluna**, e
                # nenhuma das duas a tem — por isso nao entram aqui nem precisam
                # de entrada em `ci/rls_exceptions.yaml`. O que isola o inbox e
                # um **papel**, o `kamba_pay_hooks`, e nao uma politica.
                #
                # **Nenhuma das duas tem receita de sementes**, e as razoes
                # estao em `sementes.SEM_RECEITA_COM_RAZAO`, uma por tabela: no
                # ledger ninguem tem `INSERT` e o `deny_mutation` recusa o
                # `DELETE` com que estas receitas limpam (a razao da
                # `audit_log`, a dobrar); na cobranca o *trigger*
                # `assert_beneficiary` recusa **antes** de a politica ser
                # avaliada, e o X-04 ficava a medir a guarda G-1 em vez do
                # `WITH CHECK`. As duas provam-se em `db/tests_pagamentos/`.
                ("platform", "payment_charges", "tenant_id"),
                ("platform", "payment_events", "tenant_id"),
                # KAM-043: a cotacao, depois das de pagamento
                # («pay» < «pri»). A oferta esta acima, antes de
                # `outbound_messages`.
                ("platform", "price_quotes", "tenant_id"),
                # KAM-045: a reserva de stock, entre a cotacao e o canal
                # («pri» < «sto» < «ten»). A nota do KAM-044 mais abaixo vale
                # outra vez: sao **tres** as listas deste ficheiro que
                # precisaram desta tabela, e as tres estao feitas no mesmo PR.
                ("platform", "stock_reservations", "tenant_id"),
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
                # KAM-029: a barreira de idempotencia. **Esta tem receita de
                # sementes**, ao contrario da `tool_audit`: nao e *append-only*
                # e apaga-se com `DELETE`.
                ("platform", "tool_idempotency", "tenant_id"),
                ("platform", "usage_ledger", "tenant_id"),
                # KAM-047: as quatro da agenda, no esquema `servicos`
                # (revisao `0025`). Vem **todas depois** das de `platform`,
                # porque o `ORDER BY 1, 2` da descoberta ordena primeiro por
                # esquema e «platform» < «servicos» — e dentro do esquema por
                # nome. Sao as primeiras desta lista a entrar em bloco: ate
                # aqui cada ticket trazia uma ou duas.
                #
                # **As quatro tem receita de sementes**, ao contrario da
                # `dat.llm_call_log` e da `tool_audit`: nenhuma e *append-only*,
                # e todas se apagam com `DELETE`. A ordem de apagar e a inversa
                # das chaves estrangeiras, e esta em `sementes.ORDEM`.
                ("servicos", "availability_rules", "tenant_id"),
                ("servicos", "bookings", "tenant_id"),
                ("servicos", "resources", "tenant_id"),
                ("servicos", "services", "tenant_id"),
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
            [
                # KAM-030: a particao por omissao da `dat.llm_call_log`. Entra
                # **como particao** e nao como tabela isolada, que e o que faz o
                # `verificar_particoes` exigir-lhe RLS propria e nenhum
                # privilegio — e ela tem as duas coisas: os `GRANT` da revisao
                # `0023` sao todos no pai.
                ("dat", "llm_call_log_default", "llm_call_log"),
                ("platform", "events_log_default", "events_log"),
            ],
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
        # **Todos os esquemas aplicacionais, e nao so o `platform`.** Esteve
        # preso ao `platform` enquanto todas as tabelas isoladas lá viviam; o
        # KAM-030 trouxe a primeira do `dat`, e com o filtro antigo uma entrada
        # legitima em `SEM_RECEITA_COM_RAZAO` parecia «uma porta aberta com a
        # chave perdida». O que se exclui e o mesmo que a descoberta exclui.
        todas = {
            (esquema, tabela)
            for esquema, tabela in self.consultar(
                "SELECT schemaname::text, tablename::text FROM pg_tables "
                " WHERE schemaname <> ALL(%s) "
                " AND schemaname NOT LIKE 'pg!_%%' ESCAPE '!'",
                (list(catalogo.SCHEMAS_DE_SISTEMA),),
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
                # KAM-047: as quatro do esquema `servicos`. **O `ORDER BY 1, 2`
                # do `pg_policies` e por nome de tabela e nao por esquema**,
                # pelo que elas entram misturadas com as de `platform` — ao
                # contrario da lista da descoberta, aqui em cima, que ordena
                # por esquema e as poe todas no fim.
                ("availability_rules", "tenant_iso", "ALL", "{public}"),
                ("bookings", "tenant_iso", "ALL", "{public}"),
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
                # KAM-114.
                ("draft_decisions", "tenant_iso", "ALL", "{public}"),
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
                # KAM-030: as duas do esquema `dat` (revisao `0023`). **Sao
                # duas e nao uma**: a segunda e a particao por omissao, e tem
                # politica propria porque para esta consulta — e para o
                # `verificar_particoes` — uma particao e uma tabela. Sem ela, um
                # `SELECT` dirigido a particao escapava a politica do pai.
                #
                # A consulta pede so `tablename`, pelo que a ordem e alfabetica
                # pelo nome e nao pelo esquema: depois de `hmac_key_versions`,
                # antes de `media_assets`.
                ("llm_call_log", "tenant_iso", "ALL", "{public}"),
                ("llm_call_log_default", "tenant_iso", "ALL", "{public}"),
                ("media_assets", "tenant_iso", "ALL", "{public}"),
                # KAM-015: as duas da saida de canal.
                ("message_templates", "tenant_iso", "ALL", "{public}"),
                # KAM-043: a oferta, antes de `outbound_messages`. `ALL` e
                # `{public}` como todas as outras — o
                # `rls.enable_tenant_rls` e o unico sitio onde a politica se
                # escreve, e nao toma parametros de papel.
                ("offer_terms", "tenant_iso", "ALL", "{public}"),
                # KAM-044: as **quatro** das encomendas, e no `ORDER BY 1` o
                # `_` (0x5F) vence o `s` (0x73) — as tres `order_*` vem antes da
                # `orders_mirror`. `ALL` e `{public}` nas quatro, como em todas:
                # o `rls.enable_tenant_rls` e o unico sitio onde a politica se
                # escreve. O `order_state_graph` nao aparece: nao tem
                # `tenant_id`, e e tabela de referencia.
                ("order_intents", "tenant_iso", "ALL", "{public}"),
                ("order_reconciliation_issues", "tenant_iso", "ALL", "{public}"),
                ("order_state_log", "tenant_iso", "ALL", "{public}"),
                ("orders_mirror", "tenant_iso", "ALL", "{public}"),
                ("outbound_messages", "tenant_iso", "ALL", "{public}"),
                # KAM-115: as duas do aviso ao dono, depois de
                # `outbound_messages` («ou» < «ow»).
                ("owner_contacts", "tenant_iso", "ALL", "{public}"),
                ("owner_notices", "tenant_iso", "ALL", "{public}"),
                # KAM-052: **uma** politica e nao duas. O `docs/tecnica/04`
                # secao 6.2 diz que a conta da KAMBA e «acessivel so ao papel
                # de billing» e a tentacao era acrescentar uma segunda
                # politica para esse papel, como a `resolver_leitura` da
                # `tenant_channels`. Nao se faz: o papel nao existe (divida
                # 154) e «politicas permissivas somam-se por OU», pelo que uma
                # a mais abre o que a `tenant_iso` fecha — uma porta aberta
                # sem ninguem a usar.
                #
                # **E a `0029` acrescenta-lhe a segunda, que a nota acima dizia
                # nao se fazer — e a diferenca nao e de opiniao.** A
                # `pay_hooks_token` nao e a politica de billing que o secao 6.2
                # pedia (essa continua a nao existir, divida 154): e a leitura
                # que o secao 5.1 **exige** e que nenhuma outra forma dava — no
                # instante em que um callback chega, resolver
                # `webhook_token -> conta` sem saber de que tenant e. A razao de
                # nao ser uma funcao `SECURITY DEFINER`, que era a alternativa
                # medida, esta no comentario de `_privilegios` da revisao: uma
                # `DEFINER` corre como o dono e alcanca a tabela **inteira** por
                # dentro, e punha uma segunda entrada na lista aprovada contra o
                # DoD do bloco.
                #
                # **O «somam-se por OU» continua a valer, e e exactamente por
                # isso que esta politica leva `TO`:** uma politica com `TO`
                # aplica-se **so** ao papel que nomeia, e o `OR` de que a `0027`
                # avisa junta politicas **do mesmo papel**. Nenhum outro papel e
                # nomeado aqui, pelo que a `tenant_iso` dos outros fica
                # intacta — a mesma forma da `resolver_leitura` da
                # `tenant_channels` e da `tenants`, e o que a limita e o `GRANT`
                # por coluna (sete, sem o `credenciais_ref`), nao o `USING
                # (true)`.
                #
                # `FOR SELECT` e nao `ALL`, e ordena **antes** da `tenant_iso`
                # pelo nome («pay» < «ten»).
                ("payment_accounts", "pay_hooks_token", "SELECT", "{kamba_pay_hooks}"),
                ("payment_accounts", "tenant_iso", "ALL", "{public}"),
                # KAM-053: a cobranca e o ledger. **Uma politica cada e nenhuma
                # com `TO`**: ao contrario da conta, aqui nao ha papel que leia
                # sem contexto de tenant — quem escreve no ledger e o *worker*,
                # que corre como `kamba_app` com o contexto ja resolvido (a
                # ordem do secao 5.1, `inbox.insert -> 2xx -> worker`), e o
                # `kamba_pay_hooks` nao tem privilegio nenhum nestas duas.
                #
                # A `tenant_iso` da `payment_events` e a afirmacao central deste
                # ticket, e nao e redundante com o `SECURITY DEFINER` da porta:
                # o `DEFINER` da **privilegio** e nao da **isolamento**, porque
                # o `FORCE` prende tambem o dono (`db/rls.py`, que nomeia este
                # ticket como credor da licao do KAM-052). Logo a
                # `append_payment_event` avalia a politica com o `app.tenant_id`
                # de quem chamou, e nao escreve um evento de outro tenant
                # **mesmo sendo `DEFINER`**.
                ("payment_charges", "tenant_iso", "ALL", "{public}"),
                ("payment_events", "tenant_iso", "ALL", "{public}"),
                # KAM-043: a cotacao, depois das de pagamento.
                ("price_quotes", "tenant_iso", "ALL", "{public}"),
                # KAM-047: as duas ultimas do `servicos`, e vem **antes** das
                # duas de `tenant_channels` — a ordem e por nome de tabela, e
                # `resources` < `services` < `tenant_channels`. A `tenant_channels`
                # tem **duas** politicas (a `resolver_leitura` ordena antes da
                # `tenant_iso` pelo nome), e a primeira versao desta lista pos
                # estas duas entre elas: o `ORDER BY 1, 2` e por tabela **e**
                # por politica, e so a suite contra a base o mostrou.
                ("resources", "tenant_iso", "ALL", "{public}"),
                ("services", "tenant_iso", "ALL", "{public}"),
                # KAM-045: **uma** politica, a `tenant_iso`, como as outras
                # tabelas de `platform` que nao sao lidas pelo resolvedor. Entre
                # `services` e `tenant_channels` pela colacao `C` («ser» <
                # «sto» < «ten»).
                ("stock_reservations", "tenant_iso", "ALL", "{public}"),
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
                # KAM-029: a `tool_idempotency`. Aqui o `WITH CHECK` e o que
                # impede o papel da aplicacao de **reservar** uma chave no nome
                # de outro tenant — que seria desduplicar a encomenda de um
                # cliente contra o carrinho de outro.
                ("tool_idempotency", "tenant_iso", "ALL", "{public}"),
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
             # KAM-114: as decisoes do modo concierge.
             "conversations", "draft_decisions", "entitlements",
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
             # KAM-043: a oferta entra **entre as duas** — «me» < «of» < «ou» —,
             # e e a **quinta** lista deste ficheiro a precisar de uma tabela
             # nova. As outras quatro ja estavam feitas quando esta falhou,
             # exactamente como a nota do KAM-115 tres entradas abaixo avisa: as
             # listas sao perguntas diferentes sobre a mesma tabela, e quem
             # acrescenta uma corre o *gate* 6 **inteiro**. Medido outra vez.
             "message_templates", "offer_terms",
             # KAM-044: as quatro das encomendas, e a nota de cima vale outra
             # vez — **sexta lista deste ficheiro a precisar de uma tabela
             # nova**, e as cinco anteriores ja estavam feitas quando esta
             # falhou. Quem acrescentar uma tabela isolada corre o *gate* 6
             # **inteiro**: as listas sao perguntas diferentes sobre a mesma
             # tabela. Medido outra vez, com 31 erros e 2 falhas.
             "order_intents", "order_reconciliation_issues",
             "order_state_log", "orders_mirror",
             "outbound_messages",
             # KAM-115: as duas do aviso ao dono. **Quarta lista deste ficheiro
             # a precisar delas**, e as outras tres ja estavam feitas quando esta
             # falhou — exactamente como o KAM-017 avisou duas notas acima. A
             # licao nao e sobre este ticket: quem acrescentar uma tabela isolada
             # corre o *gate* 6 **inteiro**, porque as quatro listas sao quatro
             # perguntas diferentes sobre a mesma tabela.
             "owner_contacts", "owner_notices",
             # KAM-052: a coluna de isolamento e `tenant_id` como nas outras
             # (nao e um caso de `ISOLADAS_POR_OUTRA_COLUNA`), e o predicado
             # leva o `NULLIF` da `db/rls.py` como todos.
             "payment_accounts",
             # KAM-053: a cobranca e o ledger, e as duas com a coluna
             # `tenant_id` e o predicado da `db/rls.py` como todas — o
             # `NULLIF` incluido. **Sexta lista deste ficheiro a precisar de
             # uma tabela nova**, e a licao que o KAM-043 mediu repetiu-se: as
             # cinco de cima ja estavam feitas quando esta falhou. Quem
             # acrescentar uma tabela isolada corre o *gate* 6 **inteiro**.
             #
             # Aqui o `NULLIF` vale uma frase propria: e ele que faz um
             # contexto **vazio** nao casar com linha nenhuma em vez de
             # rebentar, e e o que torna a `append_payment_event` segura sendo
             # `DEFINER` — sem contexto, a porta nao encontra a cobranca e
             # recusa, em vez de escrever no tenant errado.
             "payment_charges",
             "payment_events",
             # KAM-043: a cotacao, depois das de pagamento («pay» < «pri»).
             # A oferta esta acima, entre `message_templates` e
             # `outbound_messages`.
             "price_quotes",
             # KAM-045: a reserva de stock, entre a cotacao e o canal.
             "stock_reservations",
             "tenant_channels",
             # KAM-009: o contador e o livro. `tenant_usage` antes de
             # `tenants` pela colacao `C` do tipo `name` (ver o teste acima).
             "tenant_usage", "tenants",
             # KAM-028: a `tool_audit`, entre `tenants` e `usage_ledger`.
             # KAM-029: a `tool_idempotency`, logo a seguir — depois da
             # `tool_audit` porque `a` vem antes de `i`, e antes da
             # `usage_ledger` porque `t` vem antes de `u`.
             "tool_audit", "tool_idempotency", "usage_ledger"],
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

    def test_uma_lista_vazia_em_notacao_de_fluxo_le_se_como_lista(self) -> None:
        """`excepcoes: []` tem de dar a lista vazia, e nao a cadeia `"[]"`.

        O leitor de YAML desta casa trata o `[]` em notacao de **fluxo** a parte.
        Se devolvesse o texto, o `enumerate` do `_ler_lista` iterava os
        caracteres `[` e `]` e cada um batia no «tem de ser um mapa»: o caminho
        de **sucesso** passava a erro, e os dois ficheiros de politica do gate 6
        deixavam de se poder declarar vazios.

        **Esta propriedade estava coberta e deixou de estar.** O
        `docs/evidencia/KAM-136.md` registra a mutacao `kam136 isolamento: lista
        vazia em fluxo deixa de ser lista` como «apanhada», pelo teste
        `test_a_lista_de_excepcoes_esta_vazia` — que lia os dois ficheiros de
        `ci/` quando ambos estavam vazios. O KAM-012 encheu-os, o teste
        desapareceu com a razao de ser, e o `[]` em fluxo saiu do caminho desta
        suite: a mutacao voltou a sobreviver, na noite de 2026-10-26.

        A unica *fixture* que ainda tem um `[]` **nao** a exercita: e o caso
        `"versao"` do `test_campos_em_falta_razao_curta_e_versao_errada`, com
        `version: 2`, e o curto-circuito da versao levanta antes de a lista ser
        tocada — o `assertRaises` passa igual nos dois mundos. Por isso esta usa
        `version: 1` e afirma o sucesso.

        Os dois leitores, porque o leitor e o mesmo mas o `identificador`
        difere.
        """
        raiz = self.escrever("rls_exceptions.yaml", "version: 1\nexcepcoes: []\n")
        self.assertEqual(catalogo.excepcoes_rls(raiz), {})
        raiz = self.escrever("secdef_allowlist.yaml", "version: 1\nfuncoes: []\n")
        self.assertEqual(catalogo.funcoes_permitidas(raiz), {})

    def test_ficheiro_em_falta_levanta(self) -> None:
        raiz = Path(self.enterContext(tempfile.TemporaryDirectory()))
        with self.assertRaises(catalogo.PoliticaInvalida):
            catalogo.excepcoes_rls(raiz)
        with self.assertRaises(catalogo.PoliticaInvalida):
            catalogo.funcoes_permitidas(raiz)

    #: A chave da `append_payment_event` na allowlist, escrita **como o
    #: `pg_get_function_identity_arguments` a devolve** — isto e, com o **nome**
    #: de cada parametro antes do tipo.
    #:
    #: **E aqui que esta a armadilha que a `audit_encadear()` escondeu durante
    #: tres epics.** O comentario do `ci/secdef_allowlist.yaml` diz «`schema.
    #: nome(tipos dos argumentos)`, como `pg_get_function_identity_arguments`»,
    #: e as duas metades da frase nao dizem o mesmo: aquela funcao devolve `p_x
    #: integer`, com o nome, e nao `integer`. A primeira entrada do ficheiro nao
    #: tem argumentos nenhuns, pelo que as duas leituras coincidiam e ninguem
    #: teve de escolher; a segunda tem treze, e a diferenca passa a custar duas
    #: falhas — a funcao real «nao esta na lista» e a entrada da lista «nao
    #: existe».
    #:
    #: Nao se escreve aqui o que o ficheiro tem hoje, e a escolha e deliberada:
    #: este teste afirma o que a allowlist **tem de** conter para o
    #: `verificar_security_definer` casar com o catalogo. Escrever o que ela tem
    #: punha esta linha a passar e a deixar o X-05 vermelho, e armava a
    #: inversa — o dia em que a entrada fosse corrigida, era este teste a
    #: falhar.
    APPEND_NA_ALLOWLIST = (
        "platform.append_payment_event("
        "p_charge_id uuid, p_tipo_evento text, p_account_id uuid, "
        "p_valor_minor bigint, p_authn_method text, p_authn_ok boolean, "
        "p_decisao text, p_motivo text, p_actor_kind text, p_actor_id uuid, "
        "p_provider_event_id text, p_payload jsonb, "
        "p_ocorrido_at timestamp with time zone)"
    )

    def test_os_ficheiros_reais_leem_se_e_tem_o_que_esta_declarado(self) -> None:
        """Os dois nasceram vazios e deixaram de o estar no KAM-012.

        `ci/rls_exceptions.yaml` tem `platform.audit_heads` e
        `ci/secdef_allowlist.yaml` tem `platform.audit_encadear()` — as duas
        pelo mesmo desenho: a cabeca da cadeia de hash e escrita por um trigger
        que corre como o dono, e tem de ser, porque quem escreve a linha de
        auditoria nao pode poder escrever a cabeca.

        **A segunda funcao da allowlist e do KAM-053**, e e a unica que aquele
        ticket acrescenta — o DoD do bloco exige que seja unica. A
        `append_payment_event` e a unica porta de escrita do ledger
        `payment_events`: nenhum papel de aplicacao tem `INSERT` nessa tabela, e
        e o `DEFINER` que lhe da o privilegio que o chamador nao tem. Ela da
        privilegio e **nao** da isolamento — o `FORCE` prende tambem o dono —, e
        e por isso que a excepcao e estreita.

        A **resolucao do `webhook_token`**, que tem o mesmo problema de
        contexto, nao e uma terceira entrada: resolve-se com a politica
        `pay_hooks_token` por papel mais um `GRANT` por coluna, e a
        `resolve_webhook_token` fica `SECURITY INVOKER`. Esta lista fechada e o
        que impede que ela mude de ideias em silencio.

        Ver `APPEND_NA_ALLOWLIST` acima para a forma exacta da chave, que nao e
        a que o comentario do ficheiro parece prometer.
        """
        self.assertEqual(set(catalogo.excepcoes_rls()), {"platform.audit_heads"})
        self.assertEqual(
            set(catalogo.funcoes_permitidas()),
            {"platform.audit_encadear()", self.APPEND_NA_ALLOWLIST},
        )


if __name__ == "__main__":
    unittest.main()
