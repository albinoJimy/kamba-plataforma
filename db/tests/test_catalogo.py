"""Gate 8: o que o catalogo do PostgreSQL diz, e nao o que o DDL parece dizer.

Criterios de aceitacao 5 e 6 do KAM-003, e as linhas de isolamento e
privacidade do DoD.
"""

from __future__ import annotations

import unittest.mock

import ligacao
from tests import factories
from tests.base import (
    PRIVILEGIO_INSUFICIENTE,
    TABELAS,
    TABELAS_DAT,
    TABELAS_IDX,
    TABELAS_LG,
    TABELAS_SERVICOS,
    ComBase,
)

#: Colunas com `msisdn`, `telefone` ou `phone` no nome que sao aceites.
#:
#: O criterio de aceitacao 5 do KAM-003 da uma **lista fechada de duas** —
#: `contacts.phone_hmac` e `contact_endpoints.phone_enc`, ambas do KAM-008, que
#: as criou na revisao 0003: a primeira e um HMAC com segredo do cofre, a
#: segunda e cifra AES-256-GCM com DEK por contacto. Nenhuma guarda o numero. A
#: terceira esta aqui porque o criterio 3 do mesmo ticket **exige**
#: `tenant_channels.phone_number_id`, que contem `phone`: os dois criterios
#: contradizem-se a letra. `phone_number_id` e o identificador opaco que a Meta
#: atribui ao numero do negocio na Cloud API — nao e um telefone, nao e de um
#: cliente e nao esta em claro em sentido nenhum que o ADR-010 proteja. A
#: contradicao esta registada na verificacao do ticket e devolvida a quem
#: escreveu o criterio; a lista continua fechada, e cada entrada tem razao.
#: As duas do KAM-013 sao o **mesmo** identificador opaco da Meta que a
#: `tenant_channels` ja tinha, e nao um telefone: o `phone_number_id` e o que o
#: CHR usa para resolver o canal (KAM-014), e `inbound_events` guarda-o para que
#: o roteamento saiba de que linha o evento veio. A tabela de entrada **nao**
#: guarda o telefone do cliente em nenhuma forma — nem em claro, nem em HMAC:
#: no momento em que ela e escrita, o tenant ainda nao existe e o contacto nao
#: foi resolvido.
COLUNAS_DE_TELEFONE_ACEITES = {
    ("contacts", "phone_hmac"),
    ("contact_endpoints", "phone_enc"),
    ("tenant_channels", "phone_number_id"),
    ("inbound_events", "phone_number_id"),
    ("unrouted_events", "phone_number_id"),
    # KAM-021, revisao `0014`. **Nao e um telefone, e e um `integer`** — o
    # tecto de numeros do portfolio que o `business_capability_update` anuncia.
    # A garantia e mais forte do que a do `phone_number_id`, que e `text`: num
    # `integer` nao cabe um E.164. O nome e o da Meta, e manteve-se por isso.
    ("tenant_channels", "max_phone_numbers_per_business"),
    # KAM-016, revisao `0017`. **E o mesmo identificador opaco da Meta** que a
    # `tenant_channels`, a `inbound_events` e a `unrouted_events` ja tinham, e
    # nao um telefone: o `COMMENT` da coluna da `0001` di-lo por extenso — «Nao
    # e um telefone: e uma chave opaca da Cloud API». Esta aqui porque a
    # tentativa de onboarding tem de o guardar antes de haver canal: e ele que
    # vai bater na unicidade **global** e dar o 409 do criterio 4. **Quinta
    # entrada com este nome**, e a repeticao diz o que ha a dizer: o nome vem da
    # Meta e nao se traduz, e a lista fechada e o que impede que um telefone de
    # cliente entre num dia com este nome.
    ("channel_onboarding", "phone_number_id"),
    # KAM-087, revisao `0043`: o telefone do caso de onboarding, nas duas formas
    # que a `contacts` e a `contact_endpoints` ja tinham — cifrado em aplicacao
    # e em HMAC para o indice. Nenhuma guarda o numero em claro.
    ("onboarding_case", "phone_enc"),
    ("onboarding_case", "phone_hmac"),
}
FRAGMENTOS_DE_TELEFONE = ("msisdn", "telefone", "phone")


class TestSemTelefoneEmClaro(ComBase):
    """CA 5 e ADR-010: telefone nunca em claro e nunca como chave."""

    def colunas(self) -> list[tuple[str, str, str]]:
        return self.consultar(
            "SELECT table_name, column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = 'platform' ORDER BY 1, 2"
        )

    def test_nenhuma_coluna_de_telefone_fora_da_lista_fechada(self) -> None:
        suspeitas = {
            (tabela, coluna)
            for tabela, coluna, _ in self.colunas()
            if any(fragmento in coluna.lower() for fragmento in FRAGMENTOS_DE_TELEFONE)
        }
        self.assertEqual(
            suspeitas - COLUNAS_DE_TELEFONE_ACEITES,
            set(),
            "ha colunas de telefone fora da lista fechada",
        )

    def test_as_colunas_com_phone_sao_exactamente_as_da_lista(self) -> None:
        """Nos dois sentidos: nem uma a mais, nem uma entrada morta na lista.

        Ate ao KAM-008 so existia a da Meta; a revisao 0003 criou as outras
        duas, e a revisao 0008 (KAM-013) acrescentou as duas da entrada de
        canal — o mesmo `phone_number_id` opaco, noutras duas tabelas.
        """
        suspeitas = {
            (tabela, coluna)
            for tabela, coluna, _ in self.colunas()
            if any(fragmento in coluna.lower() for fragmento in FRAGMENTOS_DE_TELEFONE)
        }
        self.assertEqual(suspeitas, COLUNAS_DE_TELEFONE_ACEITES)

    def test_as_colunas_de_telefone_do_kam_008_nao_guardam_texto(self) -> None:
        """`bytea` nas duas: um HMAC de 32 octetos e uma cifra, nunca o numero."""
        tipos = {
            (tabela, coluna): tipo
            for tabela, coluna, tipo in self.colunas()
            if (tabela, coluna) in COLUNAS_DE_TELEFONE_ACEITES
        }
        self.assertEqual(tipos[("contacts", "phone_hmac")], "bytea")
        self.assertEqual(tipos[("contact_endpoints", "phone_enc")], "bytea")

    def test_o_telefone_nao_e_chave_de_nada(self) -> None:
        """ADR-010: nenhuma chave primaria nem FK assenta numa coluna de telefone.

        `contacts_phone_hmac_uq` e um indice unico **parcial** sobre o HMAC, para
        que dois contactos com o mesmo telefone se fundam; nao e chave primaria,
        nao e alvo de FK, e o HMAC nao e o numero.
        """
        linhas = self.consultar(
            "SELECT c.conname::text, a.attname::text FROM pg_constraint c "
            "JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY(c.conkey) "
            "WHERE c.connamespace = 'platform'::regnamespace AND c.contype IN ('p', 'f') "
            "AND (a.attname LIKE '%%phone%%' OR a.attname LIKE '%%msisdn%%' "
            " OR a.attname LIKE '%%telefone%%')"
        )
        self.assertEqual(linhas, [])

    def test_o_que_e_cifrado_e_bytea(self) -> None:
        """Uma coluna `_enc` em `text` convidava a guardar o valor em claro."""
        for tabela, coluna, tipo in self.colunas():
            if coluna.endswith("_enc"):
                with self.subTest(coluna=f"{tabela}.{coluna}"):
                    self.assertEqual(tipo, "bytea")


class TestConvencoes(ComBase):
    """Dicionario §2: identificadores, tempos e isolamento."""

    def test_so_ha_as_tabelas_declaradas(self) -> None:
        """Sem encomendas, pagamentos nem eventos: sao de outros tickets."""
        tabelas = self.consultar(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'platform' ORDER BY 1"
        )
        self.assertEqual(tuple(t for (t,) in tabelas), TABELAS)

    def test_as_chaves_primarias_sao_uuid_com_omissao_gerada(self) -> None:
        """Toda a coluna `id` e `uuid` gerada — menos uma, e essa tem razao.

        `events_outbox.id` e `bigint GENERATED ALWAYS AS IDENTITY`: e a **ordem
        de escrita** que o publicador varre (`ORDER BY id`, `docs/tecnica/06`
        §6.2), e um UUIDv4 nao tem ordem. A chave de idempotencia do evento e o
        `event_id`, que e UUIDv7. A excepcao esta escrita no dicionario §3.5
        (emenda 1.9) e e deliberada, nao esquecimento.

        `events_dlq.id` e a segunda, e a forma e a do §6.4. A razao da regra —
        uma chave sequencial vaza volume ao vizinho — nao se aplica aqui porque
        **nenhum papel sujeito a RLS le esta coluna**: `kamba_app` tem so
        `INSERT` na DLQ, e quem a le e `kamba_batch`, que e operacao da
        plataforma. Um `id` que uma pessoa escreve numa consola vale mais do que
        um UUID, e e isso que a ferramenta de operacao usa (KAM-006).
        """
        # KAM-012: a terceira, e pela mesma razao com mais forca — o
        # `kamba_app` escreve em `audit_log` e **nao le**, pelo que nenhum
        # papel sujeito a RLS ve esta coluna; e a ordem de insercao e o que
        # torna a cadeia de hash verificavel de cima a baixo.
        # KAM-028: a quarta, e a razao e exactamente a do `audit_log` — o
        # `kamba_app` escreve na `tool_audit` e **nao le** (so o `kamba_audit`
        # e o `kamba_batch` lem), pelo que nenhum papel sujeito a RLS ve esta
        # coluna. E a ordem de insercao e o que torna a cobertura do critero 5
        # ponderavel: «uma linha por invocacao `write`/`money`» le-se seguindo
        # o `id`, nao adivinhando por `ts`.
        # KAM-053: as duas do ledger, e as duas pela razao do `audit_log` com a
        # forca com que ela aqui vale mais — **nenhum papel escreve nelas pelo
        # `INSERT`**. No `payment_callbacks_inbox` escreve so o
        # `kamba_pay_hooks`, que nao ve dado de tenant nenhum (a tabela nao tem
        # `tenant_id`), pelo que nao ha papel sujeito a RLS a quem a sequencia
        # revele volume; e o `id` sequencial e o que o *worker* varre por ordem
        # de chegada, que e o que o secao 5.1 manda. Na `payment_events` nenhum
        # papel tem `INSERT` de todo — quem escreve e a `append_payment_event`,
        # que corre como o dono — e a **ordem de insercao** e o que torna a
        # cadeia de *hashes* verificavel de cima a baixo: e a razao da
        # `audit_log`, e um UUIDv4 nao tem ordem.
        por_identidade = {
            "events_outbox", "events_dlq", "audit_log", "tool_audit",
            "payment_callbacks_inbox", "payment_events",
            # KAM-054, revisao `0032`. O `fraud_signals` e sequencial pela
            # razao do `events_outbox`: nenhum papel sujeito a RLS lhe escreve
            # (a `manual_confirmar` escreve-o como dono) e a leitura e de ops.
            # Um `uuid` aleatorio tirava-lhe a ordem de chegada, que e o que um
            # painel de sinais le primeiro.
            "fraud_signals",
        }
        # **So tabelas de base**, e a restricao entrou no KAM-053 pela razao que
        # o `test_tenant_id_e_not_null_e_vem_primeiro_num_indice` ja escreve: o
        # `information_schema.columns` inclui as colunas das **vistas**, e a
        # `v_payment_events_audit` — a terceira vista do esquema — projecta o
        # `id` da `payment_events`. Uma vista nao tem chave primaria nem
        # omissao de coluna, pelo que as duas asercoes deste teste nao se lhe
        # aplicam; o `id` que ela mostra e o da tabela por baixo, e esse esta
        # afirmado duas linhas abaixo. A divisao de trabalho e a mesma: tabelas
        # aqui, vistas no `verificar_vistas` do X-05 e no `INVENTARIO`.
        linhas = self.consultar(
            "SELECT c.table_name, c.data_type, c.column_default "
            "FROM information_schema.columns AS c "
            "JOIN information_schema.tables AS t "
            "  ON t.table_schema = c.table_schema AND t.table_name = c.table_name "
            "WHERE c.table_schema = 'platform' AND c.column_name = 'id' "
            "AND t.table_type = 'BASE TABLE'"
        )
        self.assertEqual(
            {t for t, _, _ in linhas},
            {
                "tenants",
                "tenant_channels",
                "contact_endpoints",
                # KAM-013: as duas da entrada. `uuid` aleatorio e **nao**
                # identidade, e isso foi escolha: a razao que dispensa as tres
                # excepcoes acima — «nenhum papel sujeito a RLS le a coluna» —
                # nao se aplica, porque `kamba_app` **le** o `inbound_events`
                # (precisa do `RETURNING id`). Com um `id` sequencial, esse
                # papel media o volume de webhooks de toda a plataforma.
                "inbound_events",
                "unrouted_events",
                # KAM-090: a prova de aceite. `uuid` aleatorio e **nao** o
                # `bigserial` dos Detalhes Tecnicos do bloco, pela razao destas
                # duas: o `kamba_app` le-a, e um `id` sequencial dizia-lhe
                # quantos aceites a plataforma tem.
                "contract_acceptance",
                # KAM-087: o caso de onboarding e a verificacao K1, `uuid`
                # aleatorio pela regra geral: o `onboarding_id` e a referencia
                # que o registo devolve ao dono, e um sequencial dizia quantos
                # registos a plataforma tem.
                "kyc_check",
                "onboarding_case",
                # KAM-088: a decisao de screening. `uuid` aleatorio e **nao** o
                # `bigserial` do bloco, pela razao da prova de aceite: o
                # `kamba_app` le-a, e um sequencial dizia-lhe quantas decisoes
                # a plataforma toma. A ordem e a do `criado_at`.
                "screening_decision",
                # KAM-089: o caso de revisao e a decisao do revisor. `uuid`
                # aleatorio, e no registo de decisoes **nao** o `bigserial` do
                # bloco, pela razao da decisao de screening: um sequencial dizia
                # quantas decisoes a plataforma toma.
                "review_case",
                "review_decision_log",
                # KAM-049: a ingestao do Catalogo AI. `uuid` aleatorio pela
                # regra geral: o `kamba_app` le-a (precisa do `RETURNING id` da
                # foto recebida), e um sequencial dizia-lhe quantas fotos a
                # plataforma inteira recebe.
                "catalog_ingestions",
                # KAM-059: o billing da plataforma. `uuid` aleatorio pela regra
                # geral, nas cinco: o `kamba_pay` e o `kamba_app` leem as de
                # tenant sob a `tenant_iso`, e um sequencial dizia-lhes quantas
                # subscricoes, ciclos e pagamentos a plataforma tem. Na
                # `commission_accruals` e **contra** o DDL do §11.2, que a
                # escrevia de identidade — ver a revisao.
                "billing_cycles",
                "billing_ops_approvals",
                "commission_accruals",
                "price_book",
                "subscriptions",
                # KAM-014: a conversa. `uuid` aleatorio pela mesma razao: o
                # `kamba_app` le-a (precisa do `mode` e do `RETURNING`), e com
                # um `id` sequencial media quantas conversas tem a plataforma.
                "conversations",
                # KAM-015: a mensagem de saida, `uuid` aleatorio pela mesma
                # razao — o `kamba_app` le-a (precisa do `RETURNING id` do
                # `ON CONFLICT` que faz a idempotencia), e com um `id`
                # sequencial media quantas mensagens a plataforma envia. A
                # `message_templates` **nao** esta aqui: nao tem coluna `id`,
                # porque a sua chave e natural (`tenant_id`, `name`, `lang`).
                "outbound_messages",
                # KAM-021: o registo das transicoes de qualidade. `uuid`
                # aleatorio pela mesma razao das tres acima, e aqui ela e
                # directa: o `kamba_app` **le** esta tabela (precisa do
                # `SELECT` que o `ON CONFLICT (tenant_id, event_key)` exige nas
                # colunas de inferencia), e com um `id` sequencial esse papel
                # media quantas transicoes de qualidade tem a plataforma — isto
                # e, quantos canais dela estao a degradar-se.
                "channel_quality_log",
                # KAM-022: a prova de consentimento. `uuid` aleatorio **contra o
                # DDL de referencia do `docs/tecnica/10` §7.2**, que escreve
                # `bigint GENERATED ALWAYS AS IDENTITY: o `kamba_app` **le**
                # esta tabela (o `ConsentGate` pergunta pelo estado antes de
                # decidir), pelo que nao tem a propriedade que dispensa as tres
                # excepcoes acima, e com um `id` sequencial esse papel media
                # quantos consentimentos tem a plataforma — e, pela cadencia,
                # quantos clientes novos ela ve por dia. A ordem que a vista
                # `consent_actual` precisava vem do `ocorrido_em`, e o empate
                # dentro do trio e impossivel pela `consent_event_prova_uq`.
                "consent_event",
                # KAM-016: a tentativa de onboarding. `uuid` aleatorio, e aqui a
                # razao e a mesma por outro caminho: o `kamba_app` **le** esta
                # tabela — o painel da loja ve em que fase esta o canal dela —, e
                # com um `id` sequencial esse papel media **quantos clientes
                # novos a plataforma esta a ligar**, que e exactamente o numero
                # que o tecto de dez em sete dias mede. Um concorrente com uma
                # loja na plataforma lia a rampa de lancamento dela.
                "channel_onboarding",
                # KAM-017: o estado de coexistencia. `uuid` aleatorio, e a
                # razao e a mesma da linha acima por outro caminho: o
                # `kamba_app` **le e escreve** esta tabela, e com um `id`
                # sequencial o papel que trata um webhook media **quantos
                # canais a plataforma tem em coexistencia** — que e a mesma
                # rampa de lancamento que o `channel_onboarding` protege.
                "channel_coexistence",
                # KAM-115: as duas do aviso ao dono. `uuid` aleatorio, e a razao
                # e a de sempre por um caminho que importa mais do que nos
                # outros: o `kamba_app` **le e escreve** as duas, e um `id`
                # sequencial no `owner_notices` media **quantas avarias de canal
                # a plataforma tem** — que e a saude do produto inteiro, lida
                # pelo papel que trata um webhook. No `owner_contacts` mediria
                # quantos donos deram e-mail, que e a mesma rampa de lancamento
                # que o `channel_onboarding` protege.
                "owner_contacts",
                "owner_notices",
                # KAM-052: `id uuid DEFAULT gen_random_uuid()`, como a regra
                # geral. **Nao e derivada do negocio**, e a razao e o
                # `tenant_id` anulavel: uma chave composta com ele recusava a
                # conta propria da KAMBA, porque uma chave primaria nao
                # aceita NULL.
                "payment_accounts",
                # KAM-043: `id uuid DEFAULT gen_random_uuid()` na
                # `price_quotes`, pela razao das outras — o `kamba_app`
                # **le** esta tabela (o `getValidQuote` devolve o `id`, que
                # o `aceitarCotacao` usa), e com um `id` sequencial o papel
                # que atende um cliente media quantas cotacoes a plataforma
                # emite. A `offer_terms` **nao** esta aqui e nao e
                # esquecimento: nao tem coluna `id`, porque a sua chave e
                # natural e composta (`tenant_id`, `sku`) — e e isso que faz
                # da colisao de SKU entre tenants um nao-problema.
                "price_quotes",
                # KAM-053: a cobranca, `uuid` gerado **e nao de identidade**, e
                # aqui a razao nao e a das outras — e o contrario delas. O
                # secao 6.2 escreve `id = chargeId = Idempotency-Key`: **quem
                # cria a cobranca escolhe o `id`**, e e isso que torna a criacao
                # retentavel com a mesma chave (F-09). Um `bigint` de identidade
                # tirava essa escolha ao chamador e a idempotencia da criacao
                # com ela. A `payment_callbacks_inbox` e a `payment_events`
                # **nao** estao aqui, e estao no `por_identidade`: ali o que
                # importa e a ordem, aqui e a chave que o chamador traz.
                "payment_charges",
                # KAM-044: as tres das encomendas com coluna `id`, `uuid`
                # gerado. A `orders_mirror` pela razao geral — o `kamba_app`
                # **le e escreve** esta tabela, e um `id` sequencial media
                # quantas encomendas a plataforma inteira tem, lido pelo papel
                # que atende um cliente.
                #
                # O `order_state_log` **nao** esta no `por_identidade`, ao
                # contrario do que o §5.4 escreve e do que a `audit_log` faz, e
                # a razao e a mesma a olhar para o outro lado: a propriedade que
                # justifica as excepcoes de identidade — «nenhum papel sujeito a
                # RLS le a coluna» — nao se verifica aqui, porque o *trigger*
                # diferido `order_estado_exige_log` le a tabela **como
                # invocador** e por isso o `kamba_app` tem de ter `SELECT` nela.
                # Uma `SECURITY DEFINER` para o evitar lia zero linhas sob
                # `FORCE` (ver `db/rls.py`).
                #
                # O `order_intents` e o `order_state_graph` nao estao aqui e nao
                # e falta: nenhum tem coluna `id` — o primeiro tem chave natural
                # `(tenant_id, intent_key)`, que e o recibo de idempotencia, e o
                # segundo `(de, para)`, que e o par que ele declara valido.
                "orders_mirror",
                "order_state_log",
                "order_reconciliation_issues",
                # KAM-045, revisao `0033`. `uuid` aleatorio e **nao**
                # identidade, pela razao das tres acima e aqui directa: o
                # `kamba_app` **le** esta tabela (precisa do `RETURNING id` do
                # `INSERT` da reserva, e das leituras por encomenda), e com um
                # `id` sequencial esse papel media quantas reservas tem a
                # plataforma — isto e, quanto se vende nela.
                "stock_reservations",
                # KAM-054, revisao `0032`. Duas das quatro: a
                # `manual_confirmations` e a `refund_cases` tem `id` uuid
                # gerado. O `fraud_signals` esta no `por_identidade` (e
                # sequencial, pela razao do `events_outbox`), e o
                # `payment_confirmers` **nao** tem coluna `id` — a chave e
                # natural, `(tenant_id, contact_id)`, que e a pergunta que a
                # tabela responde: «este contacto deste tenant pode
                # confirmar?». Uma chave sintetica tornava a resposta uma
                # procura que pode devolver duas linhas em desacordo.
                "manual_confirmations",
                "refund_cases",
                # KAM-069, revisao `0036`. `uuid` aleatorio, e **nao** uma chave
                # natural como as linhas acima que a dispensam: a unicidade de
                # negocio e `(tenant_id, provider, country, purpose)` e o
                # `tenant_id` e **anulavel** — o nulo e o destino global de
                # infra-estrutura —, pelo que ela nao pode ser chave primaria.
                #
                # E nao e de identidade, pela razao geral: o `kamba_app` **le**
                # esta tabela (e a unica coisa que ele pode fazer nela), e com um
                # `id` sequencial esse papel media quantos destinos a plataforma
                # inteira tem registados — isto e, quantos subprocessadores e
                # quantos tenants com configuracao propria.
                "tenant_destinations",
            }
            | por_identidade,
        )
        for tabela, tipo, omissao in linhas:
            with self.subTest(tabela=tabela):
                if tabela in por_identidade:
                    self.assertEqual(tipo, "bigint")
                    self.assertIsNone(omissao, "IDENTITY nao e uma omissao de coluna")
                else:
                    self.assertEqual(tipo, "uuid")
                    self.assertEqual(omissao, "gen_random_uuid()")

    def test_as_colunas_de_identidade_sao_as_declaradas(self) -> None:
        """Uma `GENERATED AS IDENTITY` a mais era uma chave sequencial nova.

        Chaves sequenciais vazam volume (quantos pedidos tem o vizinho) e por
        isso o dicionario §2 manda `uuid`. As excepcoes tem todas a mesma
        propriedade: nenhum papel sujeito a RLS le a coluna.
        O outbox porque a tabela nao e exposta a nenhum tenant e a ordem e o que
        o publicador precisa; a `events_dlq` porque `kamba_app` tem so `INSERT`
        nela e quem a le e a operacao (KAM-006, §6.4); a `audit_log`
        (KAM-012) pela mesma razao com mais forca — o `kamba_app` **escreve e
        nao le**, e a ordem de insercao e o que torna a cadeia de hash
        verificavel por quem a le de cima a baixo; e a `tool_audit` (KAM-028)
        pela razao da `audit_log`, com a cobertura do critero 5 em vez da
        cadeia.

        **As duas do KAM-053 levam a propriedade ao limite** e por isso entram
        sem afrouxar nada: no `payment_callbacks_inbox` nenhum papel sujeito a
        RLS chega a tabela (ela nao tem `tenant_id` e so o `kamba_pay_hooks` lhe
        toca), e na `payment_events` nenhum papel tem `INSERT` de todo — quem
        escreve e a `append_payment_event`, que corre como o dono. A razao
        positiva e a da `audit_log`: a ordem de insercao e o que torna a cadeia
        de *hashes* verificavel de cima a baixo, e um UUIDv4 nao tem ordem.

        **O nome deste teste nao leva o numero, e isso e deliberado.** Levava —
        `..._sao_as_tres_declaradas` — e cada tabela nova obrigava a renomear um
        teste cujo proposito nao mudou. E a licao que o KAM-027 escreveu para as
        listas literais: um numero no nome transforma «as excepcoes sao as
        declaradas», que e a invariante, em «as excepcoes sao tres».
        """
        linhas = self.consultar(
            "SELECT c.relname::text, a.attname::text, a.attidentity "
            "FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid "
            "WHERE c.relnamespace = 'platform'::regnamespace AND a.attidentity <> '' "
            "ORDER BY 1, 2"
        )
        self.assertEqual(
            linhas,
            # `ORDER BY 1, 2`: as duas do KAM-053 entram entre `events_outbox`
            # e `tool_audit` («e» < «p» < «t»), e entre elas decide o nono
            # caracter — `payment_c` antes de `payment_e`.
            [("audit_log", "id", "a"), ("events_dlq", "id", "a"),
             ("events_outbox", "id", "a"),
             # KAM-054: entra entre `events_outbox` e `payment_callbacks_inbox`
             # («e» < «f» < «p»).
             ("fraud_signals", "id", "a"),
             ("payment_callbacks_inbox", "id", "a"),
             ("payment_events", "id", "a"),
             ("tool_audit", "id", "a")],
        )

    def test_as_chaves_primarias_sao_as_declaradas(self) -> None:
        """Todas `uuid` geradas, menos as que tem razao escrita.

        `entitlements` tem chave composta (KAM-003). `hmac_key_versions.kid` e
        `text`: e o identificador que o cofre da a versao do segredo, e nao um
        identificador que a base gere. As cinco tabelas de eventos (KAM-005) vem
        com a forma do `docs/tecnica/06` §6.1 e §6.5: `events_outbox` tem `id`
        de identidade, `events_log` tem chave composta com a coluna de particao
        (`ocorrido_em`), e os dois contadores tem chave natural.

        As quatro do consumo (KAM-006, §6.3 e §6.4) seguem a mesma ideia: a
        chave de `events_consumed` e **natural** e e o par que torna a entrega
        at-least-once num efeito exactamente-uma-vez (`consumer`, `event_id`);
        a de `evt_acoes` e a propria chave de idempotencia; a de
        `evt_dlq_aprovacoes` e `(dlq_id, aprovador)`, e e ela que torna a mesma
        pessoa a aprovar duas vezes impossivel; e a `events_dlq` tem `id` de
        identidade, pela razao escrita no teste da coluna de identidade.
        """
        linhas = self.consultar(
            "SELECT c.relname::text, a.attname::text, format_type(a.atttypid, a.atttypmod), "
            "pg_get_expr(d.adbin, d.adrelid) FROM pg_index i "
            "JOIN pg_class c ON c.oid = i.indrelid "
            "JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey) "
            "LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum "
            "WHERE i.indisprimary AND c.relnamespace = 'platform'::regnamespace "
            "ORDER BY 1, 2"
        )
        self.assertEqual(
            linhas,
            [
                # KAM-012: a chave de `audit_heads` e **gerada** e nao `uuid`
                # aleatoria, porque uma chave primaria recusa NULL e a cadeia
                # das accoes de plataforma precisa de uma linha com
                # `tenant_id` nulo (medido contra o PostgreSQL 18.6). A de
                # `audit_log` e de identidade, como a de `events_dlq`.
                ("audit_heads", "chave", "uuid",
                 "COALESCE(tenant_id, '00000000-0000-0000-0000-000000000000'::uuid)"),
                ("audit_log", "id", "bigint", None),
                # KAM-059 (revisao do billing): o ciclo e a aprovacao de ops,
                # `uuid` gerada pela regra geral. Entre a auditoria e o
                # Catalogo AI («au» < «bi» < «ca»).
                ("billing_cycles", "id", "uuid", "gen_random_uuid()"),
                ("billing_ops_approvals", "id", "uuid", "gen_random_uuid()"),
                # KAM-049 (revisao do Catalogo AI): a ingestao, `uuid` gerada
                # pela regra geral. Entre a auditoria e os canais («au» < «ca»
                # < «ch»).
                ("catalog_ingestions", "id", "uuid", "gen_random_uuid()"),
                # KAM-021: a chave e um `uuid` gerado, e a idempotencia da
                # tabela esta ao lado, na `event_key_uq` composta com o
                # `tenant_id`. Uma chave primaria derivada do evento era o
                # mesmo facto duas vezes.
                # KAM-016: a chave e um `uuid` gerado, e a chave de negocio
                # esta ao lado em **duas** unicidades — `(tenant_id, code_hash)`
                # e `(tenant_id, waba_id)` —, que e a idempotencia do criterio 2.
                # Uma chave primaria composta por `(tenant_id, waba_id)` era a
                # alternativa, e nao se escolheu: a compensacao e a transicao
                # referem uma tentativa pelo `id`, e uma chave de duas colunas
                # obrigava cada caminho a carregar as duas. **A posicao e antes
                # da de qualidade**: a lista esta ordenada e «channel_o» vence
                # «channel_q» porque 'o' < 'q' — a primeira versao poe-a antes
                # da `consent_event` e o gate 8 recusou-a por isso.
                # KAM-017: a chave e um `uuid` gerado, e a chave de negocio
                # esta ao lado na `channel_coexistence_canal_uq`
                # `(tenant_id, channel_id)` — que e o que faz o «sem criar
                # canal duplicado» do criterio 9 ser propriedade da base. **A
                # posicao e antes da de onboarding**: a lista esta ordenada e
                # «channel_c» vence «channel_o» porque 'c' < 'o'.
                ("channel_coexistence", "id", "uuid", "gen_random_uuid()"),
                ("channel_onboarding", "id", "uuid", "gen_random_uuid()"),
                ("channel_quality_log", "id", "uuid", "gen_random_uuid()"),
                # KAM-115: as duas do aviso ao dono. A posicao e **depois** da
                # `message_templates` e antes da `tenant_channels`, porque a
                # lista esta ordenada e 'o' fica entre 'm' e 't'. As duas tem
                # chave `uuid` gerada e a chave de negocio ao lado: a
                # `owner_contacts_canal_uq (tenant_id, canal)` e a
                # `owner_notices_idempotencia_uq (tenant_id, chave, lembrete,
                # canal)`, que e a idempotencia do criterio 2 e os lembretes do
                # criterio 4 na mesma restricao.
                # KAM-022: a chave da prova e um `uuid` gerado, e a
                # idempotencia do criterio 2 esta ao lado, na
                # `consent_event_prova_uq` composta com o `tenant_id` — o
                # `evidence_hash` leva o `wamid` e a hora **da Meta**, pelo que
                # uma reentrega do mesmo botao da o mesmo resumo. A chave da
                # `consent_texts` e **natural**, `(version, purpose)`: uma
                # versao do aviso identifica-se pelo numero que lhe foi dado e
                # pela finalidade que descreve, e um `uuid` ali era um
                # identificador que ninguem citaria.
                # KAM-059: a sombra da comissao, `uuid` gerada e **nao** a
                # identidade do §11.2 — o `kamba_app` e o `kamba_pay` leem-na
                # sob a `tenant_iso`, e uma sequencia dizia quantos pagamentos
                # autenticados tem a plataforma («com» < «con»).
                ("commission_accruals", "id", "uuid", "gen_random_uuid()"),
                ("consent_event", "id", "uuid", "gen_random_uuid()"),
                ("consent_texts", "purpose", "text", None),
                ("consent_texts", "version", "text", None),
                ("contact_deks", "dek_id", "uuid", "gen_random_uuid()"),
                ("contact_endpoints", "id", "uuid", "gen_random_uuid()"),
                ("contacts", "contact_id", "uuid", "gen_random_uuid()"),
                # KAM-090, revisao `0040`: as duas seguem a regra geral, `uuid`
                # gerado. A da prova chama-se `id` e **nao** e o `bigserial`
                # dos Detalhes Tecnicos do bloco, pela razao da `consent_event`
                # (emenda 1.28): o `kamba_app` le-a, e uma chave sequencial dizia
                # quantos aceites a plataforma tem. A chave de negocio de cada
                # uma esta ao lado: `(onboarding_id, document_id, versao)` na
                # prova, `(tipo, versao)` na versao publicada. A posicao e por
                # `ORDER BY 1, 2`: «contr» depois de «conta» e antes de «conv».
                ("contract_acceptance", "id", "uuid", "gen_random_uuid()"),
                ("contract_document", "document_id", "uuid", "gen_random_uuid()"),
                # KAM-014: a chave da conversa e um `uuid` gerado, e a
                # unicidade de negocio — uma conversa por (tenant, contacto,
                # canal) — e uma `UNIQUE` ao lado. A chave composta era a
                # alternativa, e nao se escolheu: sete tickets vao referir uma
                # conversa por `conversation_id`, a comecar pelo contrato
                # `agent_invocation` deste, e uma chave de tres colunas
                # obrigava cada um a carregar as tres.
                ("conversations", "id", "uuid", "gen_random_uuid()"),
                # KAM-114: o `draft_id` e `sha256(thread_id:turn_seq)`, com
                # `CHECK` de forma hexadecimal. Chave primaria e nao indice
                # unico, porque a idempotencia do `draft_prepare` e da base.
                ("draft_decisions", "draft_id", "text", None),
                # KAM-070, revisao `0038`: o pedido do titular segue a regra
                # geral, `uuid` gerado — e a chave **nao se chama `id`**, o que
                # a tira do conjunto fechado do
                # `test_as_chaves_primarias_sao_uuid_com_omissao_gerada`, que
                # pergunta pela coluna `id`. O nome e o do dominio: um
                # `dsar_id`, que e o que o criterio 3 cita e o que o ledger
                # referencia por FK composta.
                #
                # **A chave de negocio nao e esta e nao e unica no tempo**: dois
                # pedidos do mesmo tipo pelo mesmo titular sao legitimos em
                # meses diferentes, pelo que a unicidade do criterio 8 e um
                # indice **parcial** sobre os estados abertos e nao uma chave. A
                # `dsar_requests_tenant_dsar_uq` ao lado nao e chave de negocio
                # nenhuma: existe para o ledger poder apontar para o par
                # `(tenant_id, dsar_id)`.
                #
                # A posicao e por `ORDER BY 1, 2`: depois de `draft_decisions`
                # («dra» < «dsa») e antes de `entitlements`.
                ("dsar_requests", "dsar_id", "uuid", "gen_random_uuid()"),
                ("entitlements", "modulo", "text", None),
                ("entitlements", "tenant_id", "uuid", None),
                # KAM-070, idem, e a mesma razao para o nome: um `erasure_id`, e
                # nao um `id`. A chave de negocio e a unicidade
                # `(tenant_id, dsar_id, escopo)` ao lado — e **ela** e que conta
                # os seis escopos do criterio 3 —, e nao pode ser a chave
                # primaria por uma razao de forma: as tres colunas sao duas FK e
                # um dominio fechado, e a linha que falta identificar numa
                # reaplicacao depois de um restauro (criterio 6) e a que o
                # `tenant_id, contact_id, aplicado_at` encontra.
                #
                # A posicao e por `ORDER BY 1, 2`: depois de `entitlements`
                # («ent» < «era») e antes de `events_consumed`.
                ("erasure_ledger", "erasure_id", "uuid", "gen_random_uuid()"),
                ("events_consumed", "consumer", "text", None),
                ("events_consumed", "event_id", "uuid", None),
                ("events_dlq", "id", "bigint", None),
                ("events_log", "event_id", "uuid", None),
                ("events_log", "ocorrido_em", "timestamp with time zone", None),
                ("events_log_default", "event_id", "uuid", None),
                ("events_log_default", "ocorrido_em", "timestamp with time zone", None),
                ("events_outbox", "id", "bigint", None),
                ("evt_acoes", "idempotency_key", "text", None),
                ("evt_agregado_seq", "agregado_id", "text", None),
                ("evt_agregado_seq", "agregado_tipo", "text", None),
                ("evt_agregado_seq", "tenant_id", "uuid", None),
                ("evt_dlq_aprovacoes", "aprovador", "text", None),
                ("evt_dlq_aprovacoes", "dlq_id", "bigint", None),
                ("evt_subscricoes", "consumer", "text", None),
                ("evt_subscricoes", "tipo", "text", None),
                # KAM-019: a chave da conta de atendimento e **natural**,
                # `(tenant_id, provedor)`, e e isso que torna «uma conta por
                # PME» (criterio 1) uma propriedade da base e nao do codigo —
                # um `ensureAccount` concorrente bate na chave. A do
                # `provedor` vem primeiro nesta lista porque a consulta e
                # `ORDER BY 1, 2`.
                # KAM-054, revisao `0032`. As quatro da confirmacao humana,
                # e cada uma com a forma que a sua pergunta pede. O
                # `fraud_signals` e sequencial (`bigint` de identidade) pela
                # razao do `events_outbox`; a `manual_confirmations` e a
                # `refund_cases` levam `uuid` gerado; e o
                # `payment_confirmers` tem chave **natural e composta**,
                # `(tenant_id, contact_id)` — e e a segunda tabela do
                # esquema com chave composta por `tenant_id` a frente,
                # depois da `offer_terms` da `0028`. A posicao de cada uma e
                # por `ORDER BY 1, 2`: `fr` antes de `ha`, `ma` depois de
                # `lg`/`media`, `pa` para o par dos confirmadores e `re`
                # depois de `price_quotes`.
                ("fraud_signals", "id", "bigint", None),
                ("handoff_accounts", "provedor", "text", None),
                ("handoff_accounts", "tenant_id", "uuid", None),
                # KAM-019: a chave da passagem e **texto e derivada** —
                # `hash(thread_id, ordinal_do_handoff)`, `docs/tecnica/01`
                # §11.1 — e nao um `uuid` gerado. E a excepcao com a razao mais
                # forte desta lista: um identificador **derivado** e o que faz
                # cinco chamadas concorrentes chegarem ao mesmo valor sem se
                # falarem, que e o criterio 4, e que nenhum `gen_random_uuid()`
                # consegue. Um `uuid` aqui obrigava a uma segunda coluna com o
                # resumo e a unicidade nela — a mesma coisa com um nivel de
                # indireccao a mais.
                ("handoffs", "handoff_id", "text", None),
                ("hmac_key_versions", "kid", "text", None),
                # KAM-013: `uuid` aleatorio, pela razao escrita no teste da
                # coluna de identidade. A chave de deduplicacao **nao** e esta:
                # e o `UNIQUE (kind, event_key)`, que e uma restricao propria.
                ("inbound_events", "id", "uuid", "gen_random_uuid()"),
                # KAM-020: `uuid` aleatorio, e aqui a escolha e o **contrario**
                # da `handoffs` quatro linhas acima, de proposito. A
                # idempotencia desta tabela nao e a chave primaria: e a
                # `media_assets_origem_uq (tenant_id, wamid, media_id)`, que ja
                # e derivada do que a mensagem traz. Uma chave primaria
                # derivada seria o mesmo facto duas vezes, e o `asset_id`
                # existe para outra coisa — e o que o criterio 5 poe em
                # `media://{asset_id}`, e tem de ser estavel quando a chave do
                # objecto mudar de molde.
                # KAM-087 (0043): a verificacao K1, `uuid` gerada pela regra
                # geral, antes de `manual_confirmations` («ky» < «ma»).
                ("kyc_check", "id", "uuid", "gen_random_uuid()"),
                ("manual_confirmations", "id", "uuid", "gen_random_uuid()"),
                ("media_assets", "asset_id", "uuid", "gen_random_uuid()"),
                # KAM-015: a chave do template e **natural e de texto**
                # — `(tenant_id, name, lang)`, como o `docs/tecnica/01` §8.3 —
                # porque um template e identificado pelo que a Meta conhece, e
                # nao por um identificador nosso. O §2 pede `uuid` para a
                # coluna que **referencia**, e nada referencia esta tabela por
                # chave estrangeira: a `outbound_messages.template_name` e um
                # `text` solto, e uma FK pediria `(tenant_id, template_name,
                # lang)` — e a `outbound_messages` nao tem coluna `lang`.
                #
                # A posicao nesta lista nao e indiferente: a consulta e
                # `ORDER BY 1, 2` e a comparacao e de listas ordenadas. Pus
                # estas quatro linhas depois de `entitlements` na primeira
                # versao e o teste falhou — com razao.
                ("message_templates", "lang", "text", None),
                ("message_templates", "name", "text", None),
                ("message_templates", "tenant_id", "uuid", None),
                # KAM-015: um `uuid` gerado, como a conversa, e pela mesma
                # razao — a unicidade de negocio (a chave de idempotencia) e
                # uma `UNIQUE` ao lado, e varios tickets a jusante vao referir
                # uma mensagem enviada por um identificador so.
                # KAM-043: a **primeira chave primaria composta do esquema**
                # que nao e de contadores nem de chave natural de texto —
                # `(tenant_id, sku)` — e nao e estilo: e o que faz do mesmo
                # texto de `sku` em dois tenants duas linhas independentes,
                # que e a colisao de SKU entre tenants (ISO-33..38) resolvida
                # por construcao em vez de por predicado. O `ORDER BY 1, 2`
                # poe o `sku` antes do `tenant_id` ("sk" < "te"), e nao a
                # ordem da chave; e poe a tabela antes de `outbound_messages`
                # ("of" < "ou").
                ("offer_terms", "sku", "text", None),
                ("offer_terms", "tenant_id", "uuid", None),
                # KAM-087 (0043): o caso de onboarding, `uuid` gerada; entre a
                # oferta e as encomendas («off» < «onb» < «ord»).
                ("onboarding_case", "id", "uuid", "gen_random_uuid()"),
                # KAM-044: as cinco das encomendas, e tres formas diferentes.
                #
                # O `order_intents` tem chave **natural e composta**,
                # `(tenant_id, intent_key)`, e e ela o recibo de idempotencia do
                # secao 6.3: um `uuid` gerado ao lado era uma chave que nao
                # impede a segunda criacao com a mesma intencao.
                #
                # O `order_state_graph` tem chave natural `(de, para)`, como a
                # `evt_subscricoes` da `0004` e a `payment_outbox_map` da
                # `0029`: e uma tabela de referencia, e a sua identidade e o
                # par que ela declara valido. **Nao tem `tenant_id`**, e por
                # isso a chave nao comeca por ele.
                #
                # A `orders_mirror`, o `order_state_log` e o
                # `order_reconciliation_issues` seguem a regra geral, `uuid`
                # gerado. O do registo de estados **nao** e de identidade,
                # ao contrario do que o §5.4 escreve e do que a `audit_log`
                # faz: o `kamba_app` tem de ler esta tabela (e o *trigger*
                # diferido que a le, como invocador), pelo que a propriedade
                # que justifica as excepcoes de identidade — «nenhum papel
                # sujeito a RLS le a coluna» — nao se verifica aqui, e um
                # `bigint` sequencial media as transicoes de toda a
                # plataforma. A razao esta escrita na revisao `0030`.
                ("order_intents", "intent_key", "text", None),
                ("order_intents", "tenant_id", "uuid", None),
                ("order_reconciliation_issues", "id", "uuid", "gen_random_uuid()"),
                ("order_state_graph", "de", "text", None),
                ("order_state_graph", "para", "text", None),
                ("order_state_log", "id", "uuid", "gen_random_uuid()"),
                ("orders_mirror", "id", "uuid", "gen_random_uuid()"),
                ("outbound_messages", "id", "uuid", "gen_random_uuid()"),
                ("owner_contacts", "id", "uuid", "gen_random_uuid()"),
                ("owner_notices", "id", "uuid", "gen_random_uuid()"),
                # KAM-052: a chave e um `uuid` gerado, e a chave de negocio
                # esta ao lado, no indice unico parcial
                # `payment_accounts_um_ativo` sobre `(tenant_id, provider)`.
                # Uma chave primaria composta com o `tenant_id` nao servia:
                # ele e **anulavel** nesta tabela, e uma chave primaria
                # recusa NULL — foi o que obrigou a `audit_heads` a ter uma
                # coluna gerada por COALESCE. A posicao e por `ORDER BY 1, 2`:
                # depois de `owner_notices` ('ow' < 'pa').
                ("payment_accounts", "id", "uuid", "gen_random_uuid()"),
                # KAM-053: as quatro do ledger, e cada uma com uma forma
                # diferente — e as quatro diferencas sao decisoes.
                #
                # O `payment_callbacks_inbox` e a `payment_events` tem `id` de
                # identidade, pela razao escrita no teste da coluna de
                # identidade: o que se precisa delas e a **ordem**.
                #
                # A `payment_charges` tem `uuid` gerado e e o **contrario** das
                # duas: o secao 6.2 escreve `id = chargeId = Idempotency-Key`,
                # pelo que quem cria a cobranca escolhe o `id` e e isso que
                # torna a criacao retentavel (F-09). O `gen_random_uuid()` e a
                # omissao para quem nao escolhe, nao a regra.
                #
                # A `payment_outbox_map` tem chave **natural e composta**,
                # `(tipo_evento, authn_method)`, como a `evt_subscricoes` da
                # `0004` e pela mesma razao: e uma tabela de mapeamento, e a sua
                # identidade e o par que ela mapeia. Um `uuid` ao lado era um
                # identificador que nenhuma consulta citaria. O `ORDER BY 1, 2`
                # poe o `authn_method` antes do `tipo_evento`, e nao a ordem da
                # chave.
                ("payment_callbacks_inbox", "id", "bigint", None),
                ("payment_charges", "id", "uuid", "gen_random_uuid()"),
                ("payment_confirmers", "contact_id", "uuid", None),
                ("payment_confirmers", "tenant_id", "uuid", None),
                ("payment_events", "id", "bigint", None),
                ("payment_outbox_map", "authn_method", "text", None),
                ("payment_outbox_map", "tipo_evento", "text", None),
                # KAM-043: a cotacao segue a regra geral, `uuid` gerado. A
                # posicao e por `ORDER BY 1, 2`: depois de `payment_accounts`
                # ("pa" < "pr") e antes de `tenant_channels`.
                # KAM-059: o precario, `uuid` gerado («price_b» < «price_q»).
                ("price_book", "id", "uuid", "gen_random_uuid()"),
                ("price_quotes", "id", "uuid", "gen_random_uuid()"),
                # KAM-091: o estado da saga tem chave **natural e composta**, e
                # nao um `uuid` gerado — e a `UNIQUE(onboarding_id, step)` que o
                # contrato de `provisioning/contrato.ts` declara, promovida a
                # chave. Pela razao da `payment_outbox_map` e das duas tabelas
                # de uso: a identidade da linha **e** o par, e um `id` ao lado
                # era um identificador que nenhuma consulta citaria.
                #
                # E ha uma razao a mais, que nao vale para aquelas: **nenhuma
                # das oito portas do contrato recebe um `id` de linha** — as
                # seis de escrita e as duas de leitura chaveiam pelo
                # `onboardingId`, so ou com o passo —, e uma
                # unicidade com o `tenant_id` a frente — a escolha da
                # `stock_reservations` tres linhas abaixo — deixava o
                # `ON CONFLICT (onboarding_id, step)` do `abrir` sem restricao
                # que casasse, e nenhum dos cinco `marcar*` recebe um
                # `tenant_id` para completar o terno.
                #
                # Duas linhas, que e o `ORDER BY 1, 2` sobre as duas colunas da
                # chave — `onboarding_id` antes de `step`, e nao a ordem da
                # chave, que e a mesma por coincidencia.
                ("provisioning_step", "onboarding_id", "uuid", None),
                ("provisioning_step", "step", "text", None),
                # KAM-071 (0042). `uuid` gerada, como as outras: uma linha de
                # purga nao tem chave natural, e a unidade (classe, tabela,
                # tenant) repete-se a cada execucao de proposito.
                ("purge_log", "purge_id", "uuid", "gen_random_uuid()"),
                ("refund_cases", "id", "uuid", "gen_random_uuid()"),
                # KAM-089 (0048): o caso de revisao e o registo de decisoes,
                # pela regra geral. Entre o caso de reembolso e a decisao de
                # screening («ref» < «rev» < «scr»).
                ("review_case", "id", "uuid", "gen_random_uuid()"),
                ("review_decision_log", "id", "uuid", "gen_random_uuid()"),
                # KAM-088 (0044): a decisao de screening, `uuid` gerada pela
                # regra geral e nao o `bigserial` do bloco — um sequencial
                # dizia quantas decisoes a plataforma toma. Entre o caso de
                # reembolso e a reserva de stock («ref» < «scr» < «sto»).
                ("screening_decision", "id", "uuid", "gen_random_uuid()"),
                # KAM-045: a reserva de stock segue a regra geral, `uuid`
                # gerado. A posicao e por `ORDER BY 1, 2`: depois de
                # `refund_cases` ("re" < "st") e antes de `tenant_channels`.
                ("stock_reservations", "id", "uuid", "gen_random_uuid()"),
                # KAM-059: a subscricao, `uuid` gerado («st» < «su» < «te»).
                ("subscriptions", "id", "uuid", "gen_random_uuid()"),
                ("tenant_channels", "id", "uuid", "gen_random_uuid()"),
                # KAM-069: os destinos de transferencia seguem a regra geral,
                # `uuid` gerado — e **nao** a chave natural das linhas acima,
                # por uma razao que nao e de gosto: a unicidade de negocio e
                # `(tenant_id, provider, country, purpose)` e o `tenant_id` e
                # **anulavel** (o nulo e o destino global de infra-estrutura,
                # criterio 1), pelo que nao pode ser chave primaria — uma chave
                # primaria nao aceita nulos. A unicidade fica ao lado, com
                # `NULLS NOT DISTINCT`, sem o qual dois destinos globais para o
                # mesmo trio passavam os dois.
                #
                # A posicao e por `ORDER BY 1, 2`: depois de `tenant_channels`
                # ("tenant_ch" < "tenant_de") e antes de `tenant_usage`.
                ("tenant_destinations", "id", "uuid", "gen_random_uuid()"),
                # KAM-009: as duas tabelas de uso tem chave **composta e de
                # negocio**, e nao um `uuid` gerado. E deliberado: a chave de
                # `tenant_usage` e o que torna «um contador por tenant, chave
                # e periodo» impossivel de violar, e a de `usage_ledger` e o
                # que **recusa** a segunda chamada com a mesma chave de
                # idempotencia. Um `id` gerado ao lado delas seria uma chave
                # que nao impede nada.
                #
                # A `chave_limite` entrou na chave do `usage_ledger` com a
                # revisao adversarial: sem ela, uma chave de idempotencia
                # valia para **todas** as chaves de limite do tenant, e
                # repetir a chave de um consumo de uma mensagem autorizava um
                # pedido contra o tecto de dinheiro.
                ("tenant_usage", "chave_limite", "text", None),
                ("tenant_usage", "periodo", "date", None),
                ("tenant_usage", "tenant_id", "uuid", None),
                ("tenants", "id", "uuid", "gen_random_uuid()"),
                # KAM-028: de identidade, como a de `audit_log` e pela mesma
                # razao — `kamba_app` escreve e **nao le**, pelo que nenhum
                # papel sujeito a RLS ve esta coluna.
                ("tool_audit", "id", "bigint", None),
                # KAM-029: **natural e de texto**, como a `message_templates`, e
                # pela mesma razao com outro dono — a chave desta tabela e o
                # `sha256` do `docs/tecnica/02` §6.3, e um `uuid` gerado ao lado
                # dela era um segundo identificador para a mesma coisa. Nada a
                # referencia por chave estrangeira: o que liga esta linha a de
                # `tool_audit` e o par `(tool, args_hash)`, nao uma FK.
                ("tool_idempotency", "key", "text", None),
                ("unrouted_events", "id", "uuid", "gen_random_uuid()"),
                ("usage_ledger", "chave_limite", "text", None),
                ("usage_ledger", "idempotency_key", "text", None),
                ("usage_ledger", "tenant_id", "uuid", None),
            ],
        )

    def test_a_chave_de_tenants_chama_se_id(self) -> None:
        """Dicionario §3.2 (emenda 1.2): `id`, nao `tenant_id`."""
        linhas = self.consultar(
            "SELECT a.attname FROM pg_index i "
            "JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey) "
            "WHERE i.indrelid = 'platform.tenants'::regclass AND i.indisprimary"
        )
        self.assertEqual(linhas, [("id",)])

    def test_toda_a_coluna_at_e_timestamptz(self) -> None:
        linhas = self.consultar(
            "SELECT table_name, column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = 'platform' AND column_name LIKE '%%\\_at'"
        )
        self.assertTrue(linhas, "nao encontrei colunas de tempo")
        for tabela, coluna, tipo in linhas:
            with self.subTest(coluna=f"{tabela}.{coluna}"):
                self.assertEqual(tipo, "timestamp with time zone")

    def test_nao_ha_timestamp_sem_fuso_em_lado_nenhum(self) -> None:
        linhas = self.consultar(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema = 'platform' "
            "AND data_type = 'timestamp without time zone'"
        )
        self.assertEqual(linhas, [])

    #: As tabelas com `tenant_id` **anulavel**, e a razao de cada uma.
    #:
    #: **As duas da auditoria (KAM-012).** Uma accao de plataforma —
    #: `batch.run`, `breakglass.open` — nao tem tenant, e inventar-lhe um era
    #: pior: punha prova de operacao dentro da cadeia de um cliente. O
    #: `tenant_id` nulo e invisivel a politica `tenant_iso` para toda a gente,
    #: e quem escreve e le essas linhas e o `kamba_batch`, que tem
    #: `BYPASSRLS`. **Nao e um furo no isolamento: e o isolamento a
    #: funcionar** — o papel da aplicacao nao consegue escrever uma accao de
    #: plataforma nem ve que ela existe.
    #:
    #: **E a `payment_accounts` (KAM-052), que e diferente das duas e por isso
    #: tem razao propria.** Ela **guarda dados de tenant** — as contas de
    #: pagamento das PMEs — e por isso nao e dispensada de RLS: tem
    #: `tenant_iso` com `FORCE`, como todas. O que e anulavel e a linha de
    #: **uma** conta: a de `beneficiary_kind = 'plataforma_receita_propria'`,
    #: com que a KAMBA cobra a propria assinatura (`docs/tecnica/04` secao
    #: 11.2). Ela existe precisamente para nao se activar um tenant de tipo
    #: `platform`, que esta vedado em producao por D2.
    #:
    #: **A nulidade e condicional e a condicao esta na base**, o que a
    #: distingue de uma coluna frouxa: o
    #: `payment_accounts_beneficiario_ck` impoe
    #: `(beneficiary_kind = 'pme') = (tenant_id IS NOT NULL)` nos **dois**
    #: sentidos, pelo que uma conta de PME nunca tem `tenant_id` nulo e a da
    #: plataforma nunca tem tenant. Sem essa equivalencia isto seria um furo;
    #: com ela, «e de uma PME» e «tem tenant» sao o mesmo facto.
    #:
    #: Consequencia, e fica dita: sob `FORCE` a conta propria da KAMBA e
    #: invisivel a todos os papeis sujeitos a RLS e e alcancada so pelo
    #: `kamba_batch`. O `docs/tecnica/04` secao 6.2 diz «acessivel so ao papel
    #: de billing» e **esse papel nao existe** nos sete de `db/ligacao.py`;
    #: quem o vai precisar e o KAM-059. Divida documental 154.
    #:
    #: **Decisao do fundador, 2026-10-29**, depois de esta lista ter sido
    #: devolvida como barreira que o desenho do ticket contrariava. A
    #: alternativa medida era um UUID sentinela com `NOT NULL`, que nenhum
    #: documento nomeia.
    #: **E a `tenant_destinations` (KAM-069), que e a quarta e tem razao
    #: propria.** O `tenant_id` nulo nao e uma frouxidao nem uma sentinela: e um
    #: valor com significado escrito no criterio 1 do bloco — «`tenant_id` nulo
    #: significa destino global (infra)» — e corresponde aos destinos que sao da
    #: plataforma e nao de um tenant: o alojamento, as copias de seguranca, o
    #: CDN e a observabilidade.
    #:
    #: **A alternativa medida era pior.** Uma linha por tenant para o mesmo CDN
    #: era a mesma autorizacao repetida tantas vezes quantos os tenants, e a
    #: primeira que divergisse era um destino autorizado para uns e negado para
    #: outros sem ninguem decidir isso. Um UUID sentinela — a alternativa que a
    #: `payment_accounts` recusou — tinha o mesmo defeito que la: nenhum
    #: documento o nomeia.
    #:
    #: **Ao contrario da `payment_accounts`, a nulidade aqui nao e
    #: condicional**, e isso diz-se em vez de se parecer com ela: la o
    #: `payment_accounts_beneficiario_ck` faz «e de uma PME» e «tem tenant»
    #: serem o mesmo facto; aqui qualquer linha pode ser global. O que a protege
    #: e outra coisa — a politica `destinos_globais` e **`FOR SELECT`**, pelo que
    #: nenhum tenant **escreve** uma linha global, e o `kamba_app` nao tem
    #: `INSERT` nenhum nesta tabela.
    #:
    #: Consequencia, e fica dita: as linhas globais sao legiveis por **todos** os
    #: tenants, de proposito — e a segunda metade do criterio 1 («RLS `FORCE`
    #: com linhas globais legiveis»). Elas nao guardam dado de tenant nenhum:
    #: guardam quem e subprocessador da plataforma, que e informacao que a
    #: propria lista publica de subprocessadores torna publica.
    ANULAVEIS = frozenset(
        {"audit_log", "audit_heads", "payment_accounts", "tenant_destinations",
         # KAM-071 (0042). Nulo num `DROP` de particao, que e entre tenants: a
         # linha diz «larguei este mes» e o mes tem linhas de varios. As linhas
         # sem tenant so as ve quem tem `BYPASSRLS`, que e quem as escreve.
         "purge_log"}
    )

    def test_tenant_id_e_not_null_e_vem_primeiro_num_indice(self) -> None:
        """DoD: `tenant_id` presente e indexado, pronto para a RLS do KAM-004.

        Em primeiro lugar no indice, porque e o predicado que a RLS acrescenta
        a todas as consultas: num indice `(estado, tenant_id)` nao serviria.
        """
        # **So tabelas de base, e a restricao entrou no KAM-022.** O
        # `information_schema.columns` inclui as colunas das **vistas**, e a
        # `consent_actual` — a primeira vista do esquema — tem `tenant_id`.
        # Uma vista nao tem indice nem `NOT NULL`, pelo que as duas asercoes
        # deste teste nao se lhe aplicam; o que a isola e a politica da tabela
        # por baixo **mais** o `security_invoker = true`, e isso tem teste
        # proprio no `verificar_vistas` do catalogo do X-05. A divisao de
        # trabalho e essa: tabelas aqui, vistas la.
        com_tenant = self.consultar(
            "SELECT c.table_name, c.is_nullable FROM information_schema.columns AS c "
            "JOIN information_schema.tables AS t "
            "  ON t.table_schema = c.table_schema AND t.table_name = c.table_name "
            "WHERE c.table_schema = 'platform' AND c.column_name = 'tenant_id' "
            "AND t.table_type = 'BASE TABLE'"
        )
        self.assertEqual(
            {t for t, _ in com_tenant},
            {"tenant_channels", "entitlements", "contacts", "contact_deks",
             "contact_endpoints",
             # KAM-016. A tentativa de onboarding tem chave primaria `id`, que
             # **nao** leva `tenant_id` — logo indice proprio `(tenant_id,
             # fase)`, pela razao da `handoffs`, da `media_assets` e da
             # `channel_quality_log`. Os outros dois indices da tabela **nao**
             # comecam pelo `tenant_id`, e e decisao: as perguntas que
             # respondem — a janela de sete dias e a varredura dos 30 minutos —
             # nao filtram por tenant, e quem as faz tem `BYPASSRLS`.
             "channel_onboarding",
             # KAM-017. A mesma forma: chave primaria `id` sem `tenant_id`, logo
             # indice proprio `(tenant_id, estado)`. O outro indice da tabela —
             # `(estado, prazo_em)` — **nao** comeca pelo `tenant_id`, e e
             # decisao: a pergunta que responde e a varredura dos prazos, que
             # nao filtra por tenant e corre com `BYPASSRLS`.
             "channel_coexistence",
             # KAM-115. As duas do aviso ao dono, e as duas com a mesma forma:
             # chave primaria `id` sem `tenant_id`, logo indice proprio a
             # comecar por ele — `(tenant_id, canal)` no contacto e
             # `(tenant_id, gatilho, criado_at)` no aviso. Os outros indices das
             # duas **nao** comecam pelo `tenant_id`, e e decisao: as perguntas
             # que respondem — a varredura dos lembretes e a dos tenants sem
             # contacto verificado — nao filtram por tenant, porque um lembrete
             # que venceu nao e problema de uma loja; e quem as faz tem
             # `BYPASSRLS`.
             # KAM-114. A mesma forma das tres acima: chave primaria `draft_id`
             # sem `tenant_id`, logo indice proprio a comecar por ele —
             # `(tenant_id, graph_version)`, que e como a vista
             # `v_draft_metrics` agrupa. Os outros dois indices da tabela
             # **nao** comecam pelo `tenant_id`, e e decisao: a varredura dos
             # prazos filtra por `criado_at` e atravessa *tenants* com
             # `BYPASSRLS`, e a substituicao por *echo* do dono chega com o
             # `thread_id` e nao com o *tenant*.
             "draft_decisions",
             "owner_contacts",
             "owner_notices",
             # KAM-014. A conversa tem `(tenant_id, contact_id, channel_id)`,
             # que e a `UNIQUE` de negocio **e** o indice que a RLS precisa:
             # `tenant_id` em primeiro lugar, sem indice extra.
             "conversations",
             # KAM-005. O `events_log` tem o indice `(tenant_id, ocorrido_em)` e
             # a particao herda-o (o indice de uma particionada propaga-se);
             # o `events_outbox` tem `(tenant_id, criado_at)`, acrescentado ao
             # DDL do `docs/tecnica/06` §6.1 exactamente por esta regra.
             "events_outbox", "evt_agregado_seq", "events_log",
             "events_log_default",
             # KAM-006. As tres tem `(tenant_id, <tempo>)`: o `events_consumed`
             # ganhou `tenant_id` por esta regra (o §6.3 nao o tem e sem ele a
             # tabela ficava fora da RLS), e a DLQ e as accoes trazem-no do
             # envelope. A `evt_dlq_aprovacoes` **nao** esta aqui: nao tem
             # `tenant_id`, porque o isolamento do que se aprova vem da linha
             # da DLQ que ela referencia.
             "events_consumed", "events_dlq", "evt_acoes",
             # KAM-012. As duas da auditoria, com `tenant_id` anulavel — ver
             # `ANULAVEIS` logo abaixo e a razao que la esta escrita.
             # **Deixaram de ser as unicas com a `payment_accounts`**, e esta
             # frase diz-se por extenso porque era aqui que estava escrito o
             # contrario.
             "audit_log", "audit_heads",
             # KAM-052. O `tenant_id` vem primeiro no
             # `payment_accounts_tenant_idx` (`(tenant_id, estado)`), que e a
             # leitura «as contas deste tenant», e tambem no indice unico
             # parcial `payment_accounts_um_ativo`. A leitura por
             # `webhook_token` e a unica **sem** `tenant_id`, e nao pode ter:
             # quem chega num callback nao o sabe. E servida pelo indice
             # unico dessa coluna.
             "payment_accounts",
             # KAM-053. **Duas das quatro tabelas da revisao, e as outras duas
             # nao estao aqui por desenho.** A `payment_callbacks_inbox` nao tem
             # `tenant_id` porque quem chega ainda nao o revelou (secao 5.1) — o
             # que a isola e o papel estreito `kamba_pay_hooks` —, e a
             # `payment_outbox_map` e configuracao global, como a
             # `evt_subscricoes`. A descoberta pergunta pela coluna, e elas nao
             # a tem.
             #
             # As duas que estao tem `tenant_id NOT NULL` (ao contrario da
             # `payment_accounts` tres linhas acima) e chave primaria que **nao**
             # o leva — o `id`, pela razao do F-09 numa e da ordem na outra —,
             # logo indice proprio a comecar por ele: `(tenant_id, estado)` na
             # cobranca, que e a leitura «as cobrancas deste tenant neste
             # estado», e `(tenant_id, recebido_at DESC)` no ledger, que e o
             # historico. Os outros indices das duas **nao** comecam pelo
             # `tenant_id`, e e decisao: o `payment_charges_ref_uq` e por
             # `(account_id, referencia)` e nao pode levar o tenant a frente —
             # quem chega num callback nao o sabe, que e a mesma razao do
             # `webhook_token` da `payment_accounts` —, o
             # `payment_charges_activa_uq` e sobre o `COALESCE` dos dois
             # sujeitos, e o `payment_events_charge_idx` serve a leitura da
             # cadeia, que e por cobranca e nao por tenant.
             "payment_charges", "payment_events",
             # KAM-054. **As quatro da revisao `0032`**, e as quatro com
             # `tenant_id NOT NULL` — nenhuma dispensa, nenhuma entrada em
             # `ci/rls_exceptions.yaml`. O indice que serve a RLS e diferente em
             # cada uma, e nenhuma escolha e livre: o `payment_confirmers`
             # leva-o em **primeiro lugar na chave primaria** `(tenant_id,
             # contact_id)`, que e o acesso «este contacto pode confirmar?»; a
             # `manual_confirmations` tem `(tenant_id, fase, criado_at)`, que e
             # a leitura da `manual_janela`; a `refund_cases` tem
             # `(tenant_id, estado, criado_at)`, que e a fila de ops; e o
             # `fraud_signals` tem `(tenant_id, criado_at)`, que e o painel de
             # sinais. O `manual_confirmations_charge_idx` e o
             # `manual_confirmations_msg_uq` **nao** comecam pelo `tenant_id`, e
             # e decisao: os dois sao por cobranca, e a cobranca ja e de um
             # tenant so.
             "payment_confirmers", "manual_confirmations", "refund_cases",
             "fraud_signals",
             # KAM-009. O `tenant_id` vem em primeiro lugar na chave primaria
             # das duas, que e o indice que a serve — nao foi preciso indice
             # proprio para esta regra. O `usage_ledger` tem alem disso
             # `(tenant_id, periodo)`, que e por onde a retencao le.
             "tenant_usage", "usage_ledger",
             # KAM-015. As duas da saida. A `outbound_messages` tem
             # `(tenant_id, idempotency_key)`, que e a `UNIQUE` da idempotencia
             # **e** o indice que a RLS precisa; a `UNIQUE (wamid)` e global e
             # nao comeca por `tenant_id`, e nao tem de comecar — a asserçao
             # pede que **algum** indice o faca, e a razao da assimetria esta no
             # §3.14 (o `wamid` e da Meta e globalmente unico por construcao).
             # A `message_templates` tem o `tenant_id` em primeiro lugar na
             # chave primaria `(tenant_id, name, lang)`, que e o indice que a
             # serve — nao foi preciso indice proprio.
             "outbound_messages", "message_templates",
             # KAM-019. As duas do handoff, e a `handoffs` e a **primeira
             # tabela desta classe que nao satisfaz a convencao de graca**: a
             # sua chave primaria e o `handoff_id` derivado, que nao leva
             # `tenant_id`. Levou por isso um indice proprio,
             # `(tenant_id, opened_at DESC)` — e o teste recusou a primeira
             # versao da revisao, que nao o tinha. A segunda coluna e a
             # consulta do SLA que a escolhe («passagens a espera ha mais de
             # 15 min, por tenant»). A `handoff_accounts` tem o `tenant_id` em
             # primeiro lugar na chave primaria `(tenant_id, provedor)`.
             "handoffs", "handoff_accounts",
             # KAM-020. A `media_assets` e a **segunda** desta classe a nao
             # satisfazer a convencao de graca, pela mesma razao: a chave
             # primaria e o `asset_id` aleatorio. Levou indice proprio,
             # `(tenant_id, criado_at DESC)`, e a segunda coluna e o que o
             # painel ordena. **O que ela nao levou foi um indice por
             # `retain_until`**, que e por onde a purga vai ler: essa consulta
             # e do KAM-071 e corre como `kamba_batch` (BYPASSRLS), pelo que o
             # indice que ela precisa nao e este nem tem de comecar por
             # `tenant_id` — cria-o quem a escrever, com a medida dela.
             "media_assets",
             # KAM-021. A **terceira** desta classe, e pela mesma razao: a
             # chave primaria e o `id` aleatorio. Levou indice proprio,
             # `(tenant_id, ocorrido_em DESC)`, e a segunda coluna e por onde
             # se le um historico.
             "channel_quality_log",
             # KAM-022. A **quarta** desta classe, e pela mesma razao: a chave
             # primaria e o `id` aleatorio. Levou indice proprio,
             # `(tenant_id, contact_id, purpose, ocorrido_em DESC)`, que e a
             # pergunta que a vista `consent_actual` faz — e o `tenant_id` vem
             # primeiro porque a RLS o le em toda a consulta. A
             # `consent_texts` **nao** esta aqui e nao e esquecimento: nao tem
             # `tenant_id`, porque um aviso de privacidade e um texto juridico
             # de plataforma e nao dado de tenant.
             "consent_event",
             # KAM-028. A `tool_audit` nao satisfaz a convencao de graca — a
             # chave primaria e o `id` de identidade — e levou indice proprio,
             # `(tenant_id, id)`. A segunda coluna e o `id` e nao o `ts`: toda
             # a leitura desta tabela e «as invocacoes deste tenant, por
             # ordem», e o `ts` tem empates (varias invocacoes no mesmo turno,
             # no mesmo milissegundo) enquanto o `id` nao.
             "tool_audit",
             # KAM-029. A `tool_idempotency` tambem nao satisfaz a convencao de
             # graca — a chave primaria e a `key`, que e o `sha256` do §6.3 e
             # nao leva `tenant_id` — e levou indice proprio,
             # `(tenant_id, created_at)`. A segunda coluna e a idade, que e a
             # unica pergunta por tenant que se faz a esta tabela: a leitura do
             # caminho quente e pela chave primaria, e a varredura da retencao
             # corre como `kamba_batch` sem tenant nenhum.
             "tool_idempotency",
             # KAM-043. As duas do preco opaco, e cada uma satisfaz a regra
             # por um caminho diferente. A `offer_terms` tem o `tenant_id`
             # em primeiro lugar na **chave primaria composta**
             # `(tenant_id, sku)`, que e o indice que a serve — nao foi
             # preciso indice proprio —, e tem alem disso
             # `(tenant_id, estado)` parcial em `deleted_at IS NULL`, que e
             # a leitura do catalogo publicado. O terceiro indice dela, o
             # `offer_terms_nome_trgm_idx`, **nao** comeca pelo `tenant_id`
             # e nao pode comecar: e um GIN de trigramas, e um GIN nao
             # aceita uma coluna `btree` a frente sem o `btree_gin`. A
             # asercao pede que **algum** indice comece pelo `tenant_id`, e
             # a chave primaria comeca; o que impoe o tenant na pesquisa e a
             # RLS mais o `tenant_id = $1` que o repo-base exige.
             #
             # A `price_quotes` e a **sexta** desta classe a nao satisfazer
             # a convencao de graca, pela razao das outras cinco: a chave
             # primaria e o `id` aleatorio. Levou indice proprio,
             # `(tenant_id, sku, valida_ate DESC)` parcial em
             # `estado = 'emitida'`, e a segunda e a terceira colunas sao a
             # pergunta do `getValidQuote`: «a cotacao viva deste SKU, a
             # mais recente primeiro».
             "offer_terms", "price_quotes",
             # KAM-044. As **quatro** das encomendas, e cada uma satisfaz a
             # regra por onde a sua pergunta e feita. A `orders_mirror` tem
             # indice proprio `(tenant_id, estado, criado_at DESC)`, que e o
             # `listOrders` da porta — a chave primaria e o `id` aleatorio,
             # pelo que esta e a setima desta classe a nao satisfazer a
             # convencao de graca. O `orders_mirror_expira_idx` **nao**
             # comeca pelo `tenant_id` e nao deve: o varrimento da expiracao
             # (KAM-045) corre como `kamba_batch` sobre a base toda e procura
             # por instante, nao por tenant.
             #
             # O `order_intents` satisfaz-a de graca, como a `offer_terms`: a
             # chave primaria **e** composta e comeca pelo `tenant_id`
             # (`(tenant_id, intent_key)`), que e a chave de idempotencia do
             # secao 6.3.
             #
             # O `order_state_log` satisfaz-a pela **unicidade**
             # `(tenant_id, order_id, version)`, que nao esta la para
             # indexar: e a restricao que torna «a mesma transicao gravada
             # duas vezes» um `23505`. Indexa de graca a unica pergunta que
             # se faz ao registo — o historico de uma encomenda, por versao.
             #
             # O `order_reconciliation_issues` levou indice proprio
             # `(tenant_id, estado, aberta_at)`, e a segunda e a terceira
             # colunas sao a metrica do bloco: «divergencias abertas > 5 min
             # = 0».
             "order_intents", "order_reconciliation_issues",
             "order_state_log", "orders_mirror",
             # KAM-045. A reserva de stock satisfaz a convencao pela
             # **unicidade** `(tenant_id, order_id, line_no)`, que nao esta la
             # para indexar: e a restricao do bloco (`UNIQUE (order_id,
             # line_no)`) com o `tenant_id` a frente, e a razao de ele vir a
             # frente e esta — um indice que nao principie pelo tenant nao
             # serve consulta nenhuma desta tabela. Levou tambem
             # `(tenant_id, order_id)` e `(tenant_id, estado)`, que sao as duas
             # perguntas da aplicacao: as reservas de uma encomenda e a
             # contagem de activas por tenant.
             #
             # O `stock_reservations_expira_idx` **nao** comeca pelo
             # `tenant_id`, e nao deve, pela mesma razao do
             # `orders_mirror_expira_idx` acima: o varrimento da expiracao
             # corre como `kamba_batch` sobre a base toda e procura por
             # instante, nao por tenant.
             "stock_reservations",
             # KAM-091. O estado da saga **nao** satisfaz a convencao de graca,
             # e nao por acidente: a chave primaria e composta e comeca pelo
             # `onboarding_id`, porque e esse o par que o contrato declara e o
             # unico que as portas sabem enderecar. Levou indice proprio,
             # `(tenant_id, status)`, e a segunda coluna e a pergunta do
             # `EsperadoDoTenant` da reconciliacao — «as referencias externas
             # que o `provisioning_step` tem como `concluido`» —, que e a unica
             # leitura desta tabela que atravessa casos em vez de ir a um.
             #
             # **Nao e parcial no `concluido`**, e isso e decisao: a RLS
             # acrescenta `tenant_id = ...` a **toda** a consulta, e um indice
             # parcial nao servia as que nao sao da reconciliacao.
             #
             # O `tenant_id` e `NOT NULL` e **nao tem FK** para `tenants` — o
             # passo 1 da saga e que escreve essa linha —, pelo que o que o
             # isola e so a politica `tenant_iso`.
             "provisioning_step",
             # KAM-069. Satisfaz a convencao **pela unicidade**, como a
             # `conversations` e a `stock_reservations`: a
             # `UNIQUE NULLS NOT DISTINCT (tenant_id, provider, country,
             # purpose)` principia pelo `tenant_id`, e nao esta la para indexar
             # — e a restricao do criterio 1.
             #
             # O indice proprio que a tabela tem (`(provider, purpose)
             # WHERE tenant_id IS NULL`) **nao** comeca pelo `tenant_id`, e nao
             # deve: serve o **outro** acesso, as linhas globais, que a porta le
             # em todas as consultas e que um indice com o nulo a cabeca nao
             # serve (um `IS NULL` sobre a primeira coluna de um indice de
             # quatro varre-o todo).
             #
             # **E a unica desta lista cujo `tenant_id` e anulavel**, pela razao
             # escrita em `ANULAVEIS`.
             "tenant_destinations",
             # KAM-070. As duas da `0038`, e as duas satisfazem a convencao
             # **pela unicidade**, como a `conversations`, a
             # `stock_reservations` e a `tenant_destinations`: a
             # `dsar_requests_tenant_dsar_uq` e a `erasure_ledger_escopo_uq`
             # principiam pelo `tenant_id`, e nenhuma das duas esta la para
             # indexar — a primeira existe para o ledger poder apontar para o
             # par `(tenant_id, dsar_id)`, e a segunda e a contagem do
             # criterio 3.
             #
             # **Nos pedidos ha mais tres indices e os tres comecam pelo
             # `tenant_id`**: os dois parciais dos estados abertos (a
             # idempotencia do criterio 8 e o varrimento do prazo) e, no ledger,
             # o `(tenant_id, contact_id, aplicado_at)` da reaplicacao depois de
             # um restauro. Aqui nao ha o caso da `tenant_destinations` nem o do
             # `orders_mirror`, em que um indice **nao** comeca pelo tenant de
             # proposito: todas as leituras destas duas tabelas sao de um
             # tenant, incluindo a do restauro — quem a corre e o `kamba_batch`,
             # que tem contexto de tenant como os outros.
             #
             # **O `tenant_id` e `NOT NULL` nas duas**, pelo que nenhuma entra
             # em `ANULAVEIS`: um pedido do titular e sempre de um tenant, e nao
             # ha aqui o nulo com significado que o criterio 1 do KAM-069 deu
             # aos destinos globais de infra-estrutura.
             "dsar_requests", "erasure_ledger",
             # KAM-090. A prova de aceite satisfaz a convencao pelo indice
             # proprio, `(tenant_id, document_id)`, que e a pergunta do gate
             # de activacao. A unicidade `(onboarding_id, document_id, versao)`
             # **nao** comeca pelo tenant, e nao deve: e a chave do POST
             # repetido, e o caso e que a identifica. A `contract_document`
             # nao esta aqui pela razao da `consent_texts`: e texto de
             # plataforma e nao tem `tenant_id`.
             "contract_acceptance",
             # KAM-071 (0042). O indice e `(tenant_id, registado_at)`, que e a
             # leitura «as purgas deste tenant» do painel e da auditoria. O
             # `tenant_id` e anulavel — ver `ANULAVEIS`.
             "purge_log",
             # KAM-087 (0043). O caso satisfaz a convencao pela unicidade do
             # `tenant_id` pre-alocado; a verificacao K1, pelo indice
             # `kyc_check_tenant_idx`. Nenhuma tem FK para `tenants`.
             "kyc_check", "onboarding_case",
             # KAM-088 (0044). Pelo indice `screening_decision_chave_idx`, que
             # comeca pelo `tenant_id` e e a pergunta do `assertPublishable`.
             # Sem FK para `tenants`: o caso tem o tenant pre-alocado.
             "screening_decision",
             # KAM-089 (0048). Pelos indices `review_case_tenant_idx` e
             # `review_decision_log_tenant_idx`. Sem FK para `tenants`: o caso
             # de onboarding tem o tenant pre-alocado, e a linha de `tenants`
             # so nasce no passo 1 da saga.
             "review_case", "review_decision_log",
             # KAM-049 (revisao do Catalogo AI). Os tres indices comecam pelo
             # `tenant_id`: a unicidade `catalog_ingestions_media_uq` (a
             # reentrega do mesmo `media_id` da Meta), o `phash_idx` (a
             # pergunta «e o mesmo produto?») e o `fila_idx` (a fila humana).
             # **Com** FK para `tenants`: uma foto chega de um tenant ja activo.
             "catalog_ingestions",
             # KAM-059 (revisao do billing). A subscricao pela unicidade
             # `subscriptions_tenant_uq`; o ciclo pela `billing_cycles_tenant_id_uq`
             # `(tenant_id, id)`, que existe para a FK composta da cobranca; a
             # sombra e a aprovacao de ops pelos indices `_tenant_idx`. As
             # quatro com FK para `tenants`.
             "subscriptions", "billing_cycles", "commission_accruals",
             "billing_ops_approvals"},
        )
        for tabela, anulavel in com_tenant:
            with self.subTest(tabela=tabela):
                self.assertEqual(
                    anulavel, "YES" if tabela in self.ANULAVEIS else "NO",
                    "o `tenant_id` anulavel e excepcao e tem de estar em ANULAVEIS",
                )
                primeiras = self.consultar(
                    "SELECT a.attname FROM pg_index i "
                    "JOIN pg_attribute a ON a.attrelid = i.indrelid "
                    " AND a.attnum = i.indkey[0] "
                    "WHERE i.indrelid = %s::regclass",
                    (f"platform.{tabela}",),
                )
                # `audit_heads` e indexada por `chave`, que **e** o
                # `tenant_id` — `coalesce(tenant_id, zero)`, coluna gerada e
                # armazenada. O propósito da regra (o predicado que a RLS
                # acrescenta ser servido por indice) esta cumprido; a letra,
                # com outro nome. Um indice em `(tenant_id)` ao lado seria um
                # indice que nenhuma consulta usa.
                esperada = ("chave",) if tabela == "audit_heads" else ("tenant_id",)
                self.assertIn(esperada, primeiras)
    #: As colunas em unidade menor que `platform` tem, com a razao de cada uma.
    #:
    #: **Esta lista nasceu vazia, e isso era o teste e nao a regra.** Ate a
    #: revisao `0028` (KAM-043) nenhuma tabela de `platform` tinha coluna de
    #: dinheiro, pelo que a asercao «nao ha nenhuma» passava — e passava por
    #: vazio. O que o DoD do KAM-003 proibe, e o que o ADR-004 funda, e a
    #: plataforma **deter fundos**: saldos. Um preco de catalogo nao e um saldo.
    #:
    #: A distincao nao e de conveniencia, e verifica-se a seguir: `saldo`,
    #: `balance` e `_kz` continuam **proibidos sem excepcao** — os dois
    #: primeiros porque sao a coisa que o ADR-004 recusa, e o `_kz` porque e a
    #: variante que o dicionario §3.3 substitui (dinheiro e sempre `*_minor`
    #: inteiro, nunca virgula flutuante). O que passa a ter allowlist e so o
    #: `_minor`, coluna a coluna e com a razao escrita.
    #:
    #: **Isto afrouxou uma caixa de DoD de outro ticket, e a decisao esta
    #: tomada: o fundador ratificou-a a 2026-11-03.** Fica vinculativa em
    #: `docs/adr/ADR-L008-allowlist-de-colunas-em-unidade-menor.md` (KAM-172),
    #: que e o sitio a emendar se um dia o criterio mudar outra vez. A pergunta
    #: foi «Ratificas o afrouxamento da caixa do DoD que o KAM-172 descreve?» e
    #: a resposta, textual, foi «Ratifico». O que ela autoriza e **so** isto:
    #: uma coluna `*_minor` pode existir em `platform` desde que esteja
    #: declarada aqui, com a razao escrita pela qual nao e um saldo, verificada
    #: nos dois sentidos e com o tipo `bigint` afirmado. O KAM-043 entregou a
    #: medicao e a distincao; a decisao nao era dele, e deixou de estar aberta.
    #:
    #: **A ratificacao nao abre a porta ao `_kz`**, e o canario desta classe
    #: (`test_canario_os_tres_proibidos_fazem_o_teste_falhar`) e o que o prova:
    #: a metade rigida passava **pelo mesmo vazio** que esta, porque nunca
    #: houve coluna nenhuma com `saldo`, `balance` ou `_kz` em `platform`.
    #
    #: **O KAM-053 acrescentou tres entradas com a mesma pergunta ainda em
    #: aberto, e mais perto do que o ADR-004 recusa** (fechou-a a ratificacao de
    #: 2026-11-03, no paragrafo **seguinte** a este). As duas do KAM-043 sao preco
    #: de catalogo; estas sao dinheiro de **pagamento** — o montante de uma
    #: cobranca, o valor de um facto do ledger e a projeccao daquele na vista de
    #: auditoria. A distincao que as deixa passar continua a ser a mesma, e esta
    #: escrita entrada a entrada: um saldo e quantia que a plataforma **detem**
    #: e que se soma ao longo do tempo, e nenhuma destas o e — a cobranca nao
    #: muda depois de emitida (nenhum papel tem `UPDATE`), o evento e
    #: *append-only*, e o dinheiro vai da conta do cliente para a da PME, que e
    #: o que a G-1 da `0027` existe para garantir.
    #:
    #: O que **nao** mudou: `saldo`, `balance` e `_kz` continuam proibidos sem
    #: excepcao, e a asercao sobre `_minor` continua a valer **nos dois
    #: sentidos**. O KAM-053 entregou a medicao e a razao coluna a coluna com a
    #: pergunta **ainda escrita como aberta aqui** — fundiu a 2026-11-03, no
    #: mesmo dia da decisao —, e o ADR-L008 cobre as tres entradas dele. A ordem
    #: dentro do dia e INDICIO e nao se afirma: o commit tem hora, a decisao tem
    #: data. Nenhuma entrada se mexe por causa da ratificacao.
    EM_UNIDADE_MENOR = {
        # KAM-043, revisao `0028`. O preco de catalogo de um SKU: `fixo` leva o
        # preco, `a_partir_de` o minimo, `sob_consulta` e nulo (e o
        # `offer_terms_preco_ck` impoe a equivalencia nos dois sentidos). **Nao
        # e um saldo**: e um numero que o dono publica para o agente citar, e a
        # plataforma nao detem nada por causa dele.
        ("offer_terms", "preco_minor"),
        # KAM-043, idem. O total que o dono cotou para um `(sku, qty)`, com
        # validade. Tambem nao e um saldo, pela mesma razao.
        ("price_quotes", "preco_total_minor"),
        # KAM-053, revisao `0029`. O valor **desta cobranca**: o que se pediu a
        # este cliente por esta encomenda ou por este ciclo de billing.
        # **Nao e um saldo**, e aqui a distincao e a propria G-3 do
        # `docs/tecnica/04` secao 10.4 («nao existe `balance`/`wallet`»): um
        # saldo e uma quantia que a plataforma **detem** e que se soma e subtrai
        # ao longo do tempo; isto e o montante de um pedido de pagamento, que
        # nao muda depois de emitido (`payment_charges` nao tem `UPDATE` para
        # papel nenhum) e cujo dinheiro vai directo da conta do cliente para a
        # conta da PME — o que a `payment_accounts` da `0027` e a guarda G-1
        # existem para garantir. A plataforma nao fica com nada por causa desta
        # coluna, e e isso que o ADR-004 recusa.
        ("payment_charges", "amount_minor"),
        # KAM-053, idem. O valor do **facto** registado no ledger: quanto o
        # callback declarou, quanto se confirmou, quanto se reembolsou. Nao e um
        # saldo pela mesma razao, e por uma segunda que e desta tabela: uma
        # linha do ledger e *append-only* — nao se soma a nada, registra-se — e
        # a soma de eventos de uma cobranca **nao** e um saldo da plataforma, e
        # a reconstrucao de um estado (`rebuild_charge_state`).
        #
        # O `CHECK` e `>= 0` e nao `> 0` como na cobranca, de proposito: um
        # `cobranca_expirada` ou um `pagamento_orfao` sao factos de valor zero.
        ("payment_events", "valor_minor"),
        # KAM-053. **A vista, e nao e redundante com a tabela.** O
        # `information_schema.columns` lista as colunas das vistas, pelo que o
        # varrimento de `%_minor` apanha o `valor_minor` que a
        # `v_payment_events_audit` projecta — e apanha-o com razao: uma vista
        # nova que exponha uma coluna de dinheiro tem de responder a esta
        # pergunta como uma tabela. E a mesma coluna do ledger, pela mesma
        # razao, vista por quem audita.
        ("v_payment_events_audit", "valor_minor"),
        # KAM-044, revisao `0030`. O total **desta encomenda** no instante em
        # que o cliente a confirmou: a soma das linhas do `lines_snapshot`, na
        # mesma unidade menor.
        #
        # **Nao e um saldo**, e aqui a distincao e mais curta do que nas de
        # pagamento: um saldo e quantia que a plataforma **detem** e que se soma
        # e subtrai ao longo do tempo, e este numero nao se soma a nada — ele
        # **congela**. O `order_transicao_valida` recusa alterar o
        # `total_minor`, o `lines_snapshot` e a `currency` depois de a encomenda
        # sair de `criada`, pelo que a coluna e historia e nao posicao: e o que
        # o cliente aceitou pagar, guardado para que a reconciliacao do secao
        # 10.3 o possa fazer vencer contra o Registo. O dinheiro vai da conta do
        # cliente para a da PME e a plataforma nao fica com nada por causa desta
        # coluna, que e o que o ADR-004 recusa.
        #
        # E `bigint` e nao `numeric`, pela razao do §2 do dicionario, e tem
        # `currency` explicita ao lado (`orders_mirror_currency_ck`, dominio de
        # um valor).
        ("orders_mirror", "total_minor"),
        # KAM-054, revisao `0032`. O valor que **o dono escreveu** ao olhar para
        # a app do banco dele (M-4). Nao e um saldo, e aqui a distincao e mais
        # curta do que nas outras: nao e sequer um montante que a plataforma
        # peca ou receba — e o conteudo de uma resposta humana, guardado para se
        # poder auditar o desafio do valor. Anulavel: a declaracao do cliente
        # nao tem valor declarado nenhum.
        ("manual_confirmations", "valor_declarado_minor"),
        # KAM-054, idem. O montante da cobranca que se reverteu. **Nao e um
        # saldo**, e aqui a G-3 e a propria razao de a tabela existir: o
        # reembolso e processo manual **fora** da plataforma (ADR-004, G-6), a
        # KAMBA nao detem os fundos e o `refund()` do adaptador devolve
        # `NOT_SUPPORTED`. Esta coluna registra quanto a PME tem de devolver da
        # conta dela, e nao uma quantia que alguem aqui guarde.
        ("refund_cases", "valor_minor"),
        # KAM-059, revisao do billing. **Cinco, e nenhuma e um saldo**, pela
        # regra do ADR-L008, coluna a coluna:
        #
        # * `price_book.valor_minor` e o preco de um plano — o que a KAMBA pede
        #   pela assinatura —, como o `offer_terms.preco_minor` e o preco de um
        #   SKU. A plataforma nao detem nada por causa dele;
        # * `billing_cycles.valor_minor` e esse preco copiado para o ciclo ao
        #   abrir, e nao muda depois (o gatilho `billing_cycles_transicao`
        #   recusa): e o montante de **uma** factura, nao uma soma corrente;
        # * `billing_ops_approvals.valor_minor` e o valor que um de ops leu no
        #   extracto e aprovou — tem de ser igual ao da cobranca, e e por isso
        #   que existe;
        # * `commission_accruals.base_minor` e `comissao_minor` sao a **sombra**:
        #   o valor de um pagamento autenticado e o que se poderia facturar
        #   sobre ele. Nunca se factura nem se retem (ADR-004, ADR-017), e o
        #   `commission_accruals_so_sombra` impede a base de dizer o contrario.
        #   A soma delas e uma medida de *unit economics*, nao fundos detidos.
        ("price_book", "valor_minor"),
        ("billing_cycles", "valor_minor"),
        ("billing_ops_approvals", "valor_minor"),
        ("commission_accruals", "base_minor"),
        ("commission_accruals", "comissao_minor"),
        # KAM-051, revisao `0037`. **A segunda vista desta lista**, e esta aqui
        # pela razao escrita na entrada da `v_payment_events_audit`: o
        # `information_schema.columns` lista as colunas das vistas, e uma vista
        # nova que exponha uma coluna de dinheiro tem de responder a esta
        # pergunta como uma tabela.
        #
        # **E a entrada e o preco de a vista nascer no `platform`.** Esta
        # asercao filtra `table_schema = 'platform'`: a `v_oferta_viva` podia ter
        # nascido num esquema proprio e ficado **invisivel** a verificacao de
        # dinheiro, sem custar entrada nenhuma. Nasceu aqui de proposito — ser
        # vista pelo portao e a funcionalidade e nao o custo —, e a porta que
        # torna isto uma declaracao e nao uma dispensa e a que o KAM-172
        # ratificou.
        #
        # **Nao e um saldo**, e e a mesma coluna da `offer_terms` pela mesma
        # razao: um numero que o dono publica para o agente citar, e a plataforma
        # nao detem nada por causa dele. Vista por quem pesquisa, em vez de por
        # quem edita o catalogo. O que a vista acrescenta a tabela e que o valor
        # sai acompanhado de um `preco_tipo` que pode ter degradado de `fixo`
        # para `a_partir_de` — o numero e o mesmo, o que muda e como se cita.
        ("v_oferta_viva", "preco_minor"),
        # KAM-081, a `v_tenant_cost_daily`. O custo de um tenant num dia em
        # centimos de Kz, ao cambio da sessao. **Nao e um saldo**: e o que a
        # plataforma paga a terceiros (Meta, fornecedores de modelo) por servir
        # o tenant, recalculado a cada leitura e nunca guardado. Nao se soma
        # ao longo do tempo numa conta de ninguem e a plataforma nao detem
        # nada por causa dele. E `_minor` e nao `_kz`, que esta proibido acima.
        ("v_tenant_cost_daily", "custo_aoa_minor"),
    }

    def test_nao_ha_colunas_de_dinheiro_nem_saldos(self) -> None:
        """DoD: o DDL nao modela **saldos** — a plataforma nao detem fundos.

        Ver o `EM_UNIDADE_MENOR` acima para o que mudou nesta asercao com o
        KAM-043, e para a decisao do fundador que a ratificou (ADR-L008,
        2026-11-03). Que ela morde prova-se nos dois canarios abaixo.
        """
        # `saldo`, `balance` e `_kz`: **proibidos sem excepcao**. Os dois
        # primeiros sao a coisa que o ADR-004 recusa; o terceiro e a variante
        # que o dicionario §3.3 substitui, e uma coluna `*_kz` e dinheiro em
        # kwanzas inteiros ou — pior — em virgula flutuante.
        proibidas = self.consultar(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema = 'platform' AND (column_name LIKE '%%saldo%%' "
            " OR column_name LIKE '%%balance%%' OR column_name LIKE '%%\_kz')"
        )
        self.assertEqual(proibidas, [])

        # `_minor`: so as declaradas, e **nos dois sentidos**. Uma coluna nova
        # obriga a escrever a razao no `EM_UNIDADE_MENOR`; uma entrada que a
        # base nao tem e uma declaracao morta.
        em_minor = self.consultar(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema = 'platform' AND column_name LIKE '%%\_minor'"
        )
        self.assertEqual(
            set(em_minor),
            self.EM_UNIDADE_MENOR,
            "uma coluna em unidade menor nova tem de ser declarada em "
            "EM_UNIDADE_MENOR, com a razao pela qual nao e um saldo",
        )

        # E as declaradas sao **inteiras**: o dicionario §2 manda unidade menor
        # inteira e nunca virgula flutuante, e um `numeric` aqui era o defeito
        # que o nome `_minor` existe para impedir.
        for tabela, coluna in sorted(self.EM_UNIDADE_MENOR):
            with self.subTest(coluna=f"{tabela}.{coluna}"):
                tipo = self.consultar(
                    "SELECT data_type FROM information_schema.columns "
                    "WHERE table_schema = 'platform' AND table_name = %s "
                    "  AND column_name = %s",
                    (tabela, coluna),
                )
                self.assertEqual(tipo, [("bigint",)])

    #: A tabela de ensaio dos canarios do KAM-172. Nome proprio e nao
    #: `nao_devia_existir` (o das recusas de privilegio deste ficheiro):
    #: aquela nunca chega a ser criada, e esta e.
    TABELA_DE_ENSAIO = "canario_kam172"

    #: As tres colunas de ensaio do lado **rigido**, uma por metade da
    #: consulta: `saldo_x` cai no `%saldo%`, `x_balance` no `%balance%` e
    #: `x_kz` no `%\_kz` — este ultimo com o sufixo no fim, porque o padrao
    #: esta ancorado e um `kz_x` passaria de proposito.
    CANARIOS_PROIBIDOS = ("saldo_x", "x_balance", "x_kz")

    def correr_o_teste_isolado(self) -> str:
        """Corre o teste guardado com `TestResult` proprio, e devolve as falhas.

        **Nao se usa `assertRaises` sobre uma chamada directa, e a razao custou
        uma corrida do gate inteiro.** O laco do tipo do teste guardado corre
        dentro de um `subTest`, e um `subTest` **nao propaga** a falha: regista-a
        no `TestResult` corrente. Chamado de dentro de outro teste, isso dava
        duas coisas erradas ao mesmo tempo — o `assertRaises` nao via excepcao
        nenhuma **e** a falha do ensaio era contada contra o canario. Medido: a
        primeira versao do canario do tipo falhou nas duas pontas de uma so vez
        (`AssertionError not raised`, mais um `FAIL` com a mensagem do ensaio).

        Com resultado proprio, as falhas do ensaio ficam aqui — e apanham-se as
        dos `subTest` tambem, que e precisamente o que faltava.
        """
        resultado = unittest.TestResult()
        type(self)("test_nao_ha_colunas_de_dinheiro_nem_saldos").run(resultado)
        return "\n".join(
            texto for _, texto in resultado.failures + resultado.errors
        )

    def ensaiar_coluna(self, coluna: str, tipo: str = "bigint") -> str:
        """Cria `platform.<TABELA_DE_ENSAIO>(<coluna> <tipo>)`, corre o teste e limpa.

        Corre **o teste** e nao uma copia da consulta dele: uma copia prova que
        a copia morde. E a tabela de ensaio **committa**, e tem de ser — cada
        `self.consultar` abre a sua propria ligacao, e um DDL por confirmar nao
        se ve de fora da transaccao que o escreveu. O padrao e o da
        `encomendas_de_ensaio` de `test_identidade_schema.py`; a base e
        descartavel por desenho, e o trinco de `base.py` exige `kamba_gate8`.

        A limpeza esta no `finally` e e um `DROP ... IF EXISTS`: o teste falha
        de proposito no meio, e sem isso o ensaio ficava na base a avermelhar
        tudo o que corresse depois — incluindo a lista fechada de tabelas.
        """
        admin = ligacao.ligar("admin")
        admin.autocommit = True
        try:
            admin.cursor().execute(
                f"CREATE TABLE platform.{self.TABELA_DE_ENSAIO} ({coluna} {tipo})"
            )
            return self.correr_o_teste_isolado()
        finally:
            for conexao in self._conexoes:
                conexao.rollback()
            admin.cursor().execute(
                f"DROP TABLE IF EXISTS platform.{self.TABELA_DE_ENSAIO}"
            )
            admin.close()

    def test_canario_os_tres_proibidos_fazem_o_teste_falhar(self) -> None:
        """KAM-172: `saldo`, `balance` e `_kz` continuam proibidos, e morde.

        **Sem isto, a metade que continua rigida tambem passa por vazio** —
        nunca houve coluna nenhuma com estes nomes em `platform`, pelo que o
        `assertEqual(proibidas, [])` nunca disse nada sobre o que acontece
        quando uma aparecer. Era o defeito que levou ao KAM-172, no lado que a
        ratificacao de 2026-11-03 (ADR-L008) deixou de pe.

        Afirma-se tambem **porque** falhou — a mensagem tem de nomear a tabela
        de ensaio e a coluna. Sem isso, um canario fica verde com o teste a
        rebentar por outra razao, e e nessa forma que ele parece provar o que
        nao prova.
        """
        for coluna in self.CANARIOS_PROIBIDOS:
            with self.subTest(coluna=coluna):
                falhas = self.ensaiar_coluna(coluna)
                self.assertTrue(
                    falhas,
                    f"a coluna de ensaio `{coluna}` nao fez o teste falhar: "
                    "a metade rigida nao morde",
                )
                self.assertIn(self.TABELA_DE_ENSAIO, falhas)
                self.assertIn(coluna, falhas)
        # E depois dos tres, o teste volta a passar. Nao e cerimonia: afirma que
        # a limpeza do `finally` correu, e uma limpeza falhada daria um canario
        # verde sobre uma base suja.
        self.test_nao_ha_colunas_de_dinheiro_nem_saldos()

    def test_canario_a_allowlist_morde_nos_dois_sentidos(self) -> None:
        """KAM-172, «Testes Requeridos»: confirma-se que continua a morder.

        O KAM-043 escreveu a asercao nos dois sentidos; o que faltava era a
        prova de que **cada** sentido falha quando devia. Nao e redundante com o
        canario de cima: um `*_minor` nao cai na consulta dos proibidos.
        """
        # Sentido 1: coluna na base sem entrada declarada.
        falhas = self.ensaiar_coluna("ensaio_minor")
        self.assertTrue(falhas, "um `*_minor` por declarar passou")
        self.assertIn("ensaio_minor", falhas)

        # Sentido 2: entrada declarada sem coluna na base — a declaracao morta.
        # Mede-se por mutacao do proprio conjunto; criar a coluna e nao a
        # declarar e o sentido 1, e nao este.
        morta = self.EM_UNIDADE_MENOR | {("tabela_de_ensaio", "valor_minor")}
        with unittest.mock.patch.object(type(self), "EM_UNIDADE_MENOR", morta):
            falhas = self.correr_o_teste_isolado()
        self.assertTrue(falhas, "uma entrada sem coluna na base passou")
        self.assertIn("tabela_de_ensaio", falhas)

        # E com o conjunto reposto, passa.
        self.test_nao_ha_colunas_de_dinheiro_nem_saldos()

    def test_canario_uma_coluna_declarada_mas_numeric_tambem_falha(self) -> None:
        """A terceira perna da decisao ratificada: o tipo.

        O ADR-L008 vende a forma como **tres** garantias conjuntas — declarada na
        allowlist, verificada nos dois sentidos, e `bigint` e nao `numeric` —, e
        as outras duas ja tinham canario. Esta nao tinha: os ensaios criam a
        coluna como `bigint`, e a asercao do conjunto rebenta antes de o laco do
        tipo correr. **Apagar o laco do tipo inteiro nao avermelhava nada**, que
        e o defeito que este ticket existe para nao repetir, na perna que
        faltava. Achado da revisao adversarial.

        O ensaio tem de ser declarado **e** `numeric` ao mesmo tempo: declarado,
        para passar a igualdade de conjuntos e chegar ao laco; `numeric`, para o
        laco o recusar. Um `numeric` nao declarado so prova o que o canario dos
        dois sentidos ja prova.

        **E e este canario que obriga ao `correr_o_teste_isolado`:** o laco do
        tipo corre dentro de um `subTest`, que nao propaga a falha. Ver o
        docstring daquele metodo — custou uma corrida do gate inteiro a
        descobrir, e e a razao de nenhum dos tres usar `assertRaises`.
        """
        entrada = (self.TABELA_DE_ENSAIO, "ensaio_minor")
        declarada = self.EM_UNIDADE_MENOR | {entrada}
        with unittest.mock.patch.object(type(self), "EM_UNIDADE_MENOR", declarada):
            falhas = self.ensaiar_coluna("ensaio_minor", tipo="numeric")
        self.assertTrue(falhas, "um `*_minor` declarado mas `numeric` passou")
        # Falhou no laco do tipo, e nao na igualdade de conjuntos: a mensagem
        # traz o tipo medido. Sem esta linha, uma entrada mal escrita dava um
        # canario verde pela razao errada.
        self.assertIn("numeric", falhas)

        self.test_nao_ha_colunas_de_dinheiro_nem_saldos()

    def test_nao_ha_fk_para_fora_de_platform(self) -> None:
        """As FK entre `platform` e `medusa` sao logicas (texto), nunca de base."""
        linhas = self.consultar(
            "SELECT conname, confrelid::regclass::text FROM pg_constraint "
            "WHERE contype = 'f' AND connamespace = 'platform'::regnamespace"
        )
        # 13 desde o KAM-006: a `evt_dlq_aprovacoes_dlq_fk`.
        # 15 desde o KAM-009: as duas FK de `tenant_usage` e
        # `usage_ledger` para `tenants(id)`.
        # 18 desde o KAM-014: as tres da `conversations`. Duas sao **compostas
        # com o `tenant_id`** (para `contacts` e para `tenant_channels`), que e
        # o padrao que a `0003` fixou: uma conversa nao aponta para um contacto
        # nem para um canal de outro tenant, e e a base que o recusa.
        # 26 desde o KAM-019: as **tres** da `0011` — a `handoffs_tenant_fk`,
        # a `handoffs_conversation_fk` (composta, e assenta na
        # `conversations_tenant_id_uq` que a `0010` acrescentou) e a
        # `handoff_accounts_tenant_fk`. A `handoff_accounts` **nao** referencia
        # a `handoffs`: uma conta de atendimento existe antes de haver passagem
        # nenhuma.
        #
        # 23 desde o KAM-015: a `message_templates_tenant_fk` e as **quatro**
        # da `outbound_messages` — cinco, portanto. Nao sao seis: o
        # `template_name` **nao** tem
        # FK para `message_templates`: ela pediria `(tenant_id, template_name,
        # lang)` e a `outbound_messages` nao tem coluna `lang`. Tres das quatro
        # sao compostas com o `tenant_id`, pela mesma razao da `0009`: uma
        # mensagem de A nao aponta para um canal, uma conversa ou um contacto
        # de B, e nem o gate 6 nem o 3b o veriam.
        #
        # 29 desde o KAM-020: as **tres** da `media_assets` — para `tenants`,
        # e para `contacts` e `conversations` as duas **compostas** com o
        # `tenant_id`. **Nao e a tabela com mais FK do esquema** (a
        # `outbound_messages` tem quatro), e a razao de serem tres esta na
        # forma do que ela guarda: uma linha dela so faz sentido dentro de uma
        # conversa de um contacto de uma PME, e as tres FK sao as tres
        # perguntas «de quem?» que ela tem de responder.
        # 31 desde o KAM-021: as **duas** da `channel_quality_log` — para
        # `tenants` e a composta para `tenant_channels`. Duas e nao tres,
        # porque uma transicao de qualidade e do canal e nao de uma conversa:
        # nao ha contacto nem conversa a que responder «de quem?».
        # 33 desde o KAM-022: as **duas** da `consent_event` — para `tenants`
        # e a composta para `contacts`. Duas e nao tres, porque uma prova de
        # consentimento e do contacto e nao de uma conversa: o consentimento
        # vale para o titular, nao para o fio em que ele o deu. A
        # `consent_texts` nao tem FK nenhuma: nao tem `tenant_id` e a
        # finalidade e um dominio e nao uma tabela.
        # 35 desde o KAM-016: as **duas** da `channel_onboarding` — para
        # `tenants` e a composta para `tenant_channels`. Duas e nao tres, pela
        # razao das duas entradas acima: uma tentativa de onboarding e do canal
        # e nao de um contacto nem de uma conversa — no momento em que ela se
        # abre nao ha cliente nenhum na historia.
        # 37 desde o KAM-017: as **duas** da `channel_coexistence` — para
        # `tenants` e a composta para `tenant_channels`, pela razao que a
        # `0009` fixou. Duas e nao tres, pela razao das entradas acima: a
        # coexistencia e do canal e nao de um contacto nem de uma conversa.
        # 39 desde o KAM-115: **uma** de cada tabela do aviso ao dono, as duas
        # para `tenants`. Uma e nao duas, e a razao e o que o ticket e: o aviso e
        # do **dono** e nao do canal, pelo que nenhuma das duas tabelas
        # referencia `tenant_channels` — o canal, quando faz parte da historia,
        # vai dentro do `episodio`, que e texto opaco. E nenhuma referencia a
        # outra: o contacto existe sem aviso e o aviso sai sem contacto (pelo
        # painel), e uma FK entre elas tornava impossivel o caso que o criterio 6
        # manda tratar — o tenant sem contacto verificado.
        # 40 desde o KAM-114: a `draft_decisions` tem **uma** FK, para
        # `tenants`, e **nao** e composta — ela nao referencia conversa nenhuma.
        # O vinculo ao contacto e o `thread_id`, que e texto derivado e nao uma
        # FK, pela mesma razao que o `handoff_id` do §3.15 e irreversivel.
        # **41 e nao 40** desde a `0027`: a `payment_accounts_tenant_fk`, que
        # e a unica FK da conta de pagamento — o `docs/tecnica/04` secao 6
        # escreve que ela «so referencia `tenants`», e as FK para
        # `orders_mirror` sao do KAM-055 e a de `billing_cycles` do KAM-059.
        # **44 e nao 41** desde a `0028` (KAM-043): a
        # `offer_terms_tenant_fk`, a `price_quotes_tenant_fk` e a
        # `price_quotes_contacto_do_mesmo_tenant_fk`. Tres, e a terceira e
        # **composta** com o `tenant_id` — e e a correccao de 2026-10-27 do
        # `docs/tecnica/03` secao 5.4, que nomeia esta tabela por escrito:
        # com a FK simples que o bloco SQL daquele secao escreve, uma
        # cotacao de A podia apontar para um contacto de B, porque a FK e
        # satisfeita pela chave primaria de `contacts` (que nao inclui o
        # tenant) e a politica olha para o `tenant_id` da linha da cotacao,
        # que esta correcto. Medido no ISO-58 do spike KAM-041.
        #
        # A `offer_terms` tem **uma** so, e nao e falta: ela referencia o
        # tenant e mais nada. O produto vive no Registo, e o `sku` e o
        # `medusa_variant_id` sao referencias logicas (texto), nunca FK de
        # base — e a regra que o nome deste teste afirma.
        #
        # **50 e nao 44** desde a `0029` (KAM-053): as **seis** do ledger — duas
        # da `payment_charges` (`tenants` e `payment_accounts`), uma do
        # `payment_callbacks_inbox` (`payment_accounts`, e a coluna e anulavel,
        # porque um *token* que nao resolve deixa a conta em branco) e tres da
        # `payment_events` (`tenants`, `payment_charges` e `payment_accounts`).
        #
        # **Seis e nao oito**, e as duas que faltam faltam de proposito: a de
        # `order_id` para `orders_mirror` e do KAM-055 e a de `billing_cycle_id`
        # para `billing_cycles` do KAM-059, e nenhuma das duas tabelas existe. O
        # que fica **nesta** revisao e o `CHECK` de exclusividade entre os dois
        # sujeitos, que nao depende de tabela nenhuma.
        #
        # **Nenhuma das seis e composta com o `tenant_id`**, e nas tres que
        # apontam para a `payment_accounts` isso nao e uma falta mas uma
        # impossibilidade: o `tenant_id` dela e **anulavel**
        # (a conta propria da KAMBA), pelo que nao existe a unicidade
        # `(id, tenant_id)` sobre que uma FK composta assentasse. O que prende o
        # beneficiario ao tenant da cobranca e o *trigger* `assert_beneficiary`,
        # a guarda G-1 do secao 10.4, que compara os dois e recusa — e e a
        # `0029` que o liga a `payment_charges`.
        #
        # A `payment_outbox_map` nao tem FK nenhuma: e configuracao global, nao
        # tem `tenant_id`, e o `tipo_evento` e o `authn_method` sao dominios
        # fechados por `CHECK` e nao tabelas.
        #
        # **57 e nao 50** desde a `0030` (KAM-044): as **sete** das encomendas —
        # duas da `orders_mirror` (`tenants` e a composta para `contacts`), duas
        # do `order_intents` (`tenants` e a composta para `orders_mirror`), uma
        # do `order_state_log` (a composta para `orders_mirror`) e duas do
        # `order_reconciliation_issues` (`tenants` e a composta para
        # `orders_mirror`).
        #
        # **Quatro das sete sao compostas com o `tenant_id`**, e e a correccao
        # de 2026-10-27 do `docs/tecnica/03` secao 5.4 aplicada onde ela nomeia:
        # «a mesma regra vale para toda a FK entre duas tabelas com `tenant_id`
        # (`stock_reservations -> orders_mirror`, `order_state_log ->
        # orders_mirror`, `price_quotes -> contacts`), e o KAM-044 e o KAM-045
        # herdam-na daqui». As tres para `orders_mirror` assentam na
        # `orders_mirror_tenant_id_uq`, que a revisao acrescenta para isso e
        # para mais nada.
        #
        # O `order_state_log` tem **uma** so e nao duas, e e a unica diferenca
        # de forma entre ele e as outras tres: a FK composta para a
        # `orders_mirror` ja prende o `tenant_id` dele ao da encomenda, e uma
        # segunda para `tenants` nao acrescentava garantia nenhuma — prendia o
        # mesmo valor a mesma linhagem duas vezes, numa tabela *append-only*
        # cujo `INSERT` corre no caminho de toda a transicao.
        #
        # O `order_state_graph` nao tem FK nenhuma: e referencia, nao tem
        # `tenant_id`, e o `de` e o `para` sao o dominio fechado dos doze
        # estados por `CHECK` — nao uma tabela de estados, que seria uma tabela
        # de cinco linhas a dizer o que um `CHECK` diz.
        # Dez a mais com a `0032` (KAM-054): as quatro tabelas novas levam
        # `tenant_id -> tenants`, duas delas `contact_id -> contacts` e tres
        # `charge_id -> payment_charges`. A FK de `refund_cases.order_id` para
        # a `orders_mirror` **nao** esta entre elas: chegou com a `0035`
        # (KAM-055), ao lado da da `payment_charges` e pela razao escrita na
        # `0029` — pôr a FK so num dos dois lados deixava o par incoerente.
        # Duas a mais com a `0033` (KAM-045): a `stock_reservations` leva
        # `tenant_id -> tenants` e a FK **composta**
        # `(tenant_id, order_id) -> orders_mirror (tenant_id, id)`, que e a
        # licao ISO-58 do spike KAM-041 — uma FK simples deixava a reserva de A
        # apontar para a encomenda de B.
        # **72 e nao 69** desde a `0035` (KAM-055): as tres FK de `order_id`
        # para a `orders_mirror` que a `0029` e a `0032` deixaram escritas com
        # este ticket por credor — `payment_charges`, `payment_events` e
        # `refund_cases`. As tres **compostas** com o `tenant_id`, pela licao da
        # `0033` acima, e `MATCH SIMPLE`, que e o que deixa a cobranca de ciclo
        # de billing (`order_id` nulo) continuar a passar.
        #
        # **77 e nao 72** desde a `0038` (KAM-070): as **cinco** dos direitos do
        # titular — duas na `dsar_requests` (`tenant_fk` simples para `tenants`,
        # `contact_fk` **composta** `(tenant_id, contact_id)` para `contacts`) e
        # tres na `erasure_ledger` (`tenant_fk`, `dsar_fk` composta para os
        # pedidos e `contact_fk` composta para os contactos). As compostas pela
        # licao que a `0003` fixou e a `0009` repetiu: sem o `tenant_id`, o
        # pedido do titular A podia apontar para o contacto de B, e nem o
        # *gate* 6 nem o 3b o veriam.
        #
        # **Esta contagem e a terceira lista fechada que uma tabela nova custa e
        # que nao se encontra a seguir o modelo do KAM-069**: a
        # `tenant_destinations` **nao tem FK nenhuma** — um destino registra-se
        # antes de o tenant activar —, pelo que quem a tome como modelo nao passa
        # por aqui. A outra, logo acima, e o
        # `test_as_fk_nao_apagam_em_cascata`.
        #
        # **78 e nao 77** desde a `0040` (KAM-090): **uma**, a
        # `contract_acceptance_documento_fk`, composta
        # `(document_id, versao, doc_sha256)` — e composta por outra razao que
        # as do tenant: e ela que faz «um aceite cita exactamente o texto
        # publicado» ser propriedade da base. A prova **nao** tem FK para
        # `tenants` (o aceite e anterior a linha do tenant, que so nasce no
        # passo 1 da saga) e a versao publicada nao tem FK nenhuma.
        #
        # **79 e nao 78** desde a `0043` (KAM-087): **uma**, a
        # `kyc_check_caso_fk`, composta `(onboarding_id, tenant_id)` para a
        # `onboarding_case_id_tenant_uq`: uma verificacao nao junta o caso de
        # um com o tenant de outro. O caso nao tem FK nenhuma.
        #
        # **80 e nao 79** desde a `0044` (KAM-088): **uma**, a
        # `screening_decision_caso_fk`, composta `(onboarding_id, tenant_id)`
        # para a mesma unicidade do caso, pela mesma razao. O `onboarding_id`
        # e anulavel: a decisao de um produto nao tem caso.
        #
        # **82 e nao 80** desde a `0048` (KAM-089): **duas**. A
        # `review_case_caso_fk`, composta `(onboarding_id, tenant_id)` para a
        # unicidade do caso de onboarding, com o `onboarding_id` anulavel (um
        # caso de saga ou de *trust* nao tem onboarding); e a
        # `review_decision_log_case_fk`, composta `(case_id, tenant_id)` para a
        # `review_case_id_tenant_uq`: uma decisao nao junta o caso de um com o
        # tenant de outro.
        #
        # **83 e nao 82** desde a revisao do Catalogo AI (KAM-049): **uma**, a
        # `catalog_ingestions_tenant_fk`, simples para `tenants(id)`. Nao e
        # composta porque nao aponta para nada de um tenant: a tabela nao tem
        # outra FK, e a chave do STO prende-se ao tenant da linha por `CHECK`
        # (`catalog_ingestions_media_ref_ck`) e nao por FK.
        #
        # **92 e nao 83** desde a revisao do billing (KAM-059): **nove**. Quatro
        # simples para `tenants(id)` (`subscriptions_`, `billing_cycles_`,
        # `commission_accruals_` e `billing_ops_approvals_tenant_fk`); a
        # `commission_accruals_evento_fk` para `payment_events(id)` e a
        # `billing_ops_approvals_charge_fk` para `payment_charges(id)`, simples
        # porque o gatilho e a porta conferem o tenant; e tres **compostas** pela
        # licao ISO-58 — a `charges_billing_fk` (cobranca -> ciclo), a
        # `billing_cycles_subscricao_do_mesmo_tenant_fk` e a
        # `commission_accruals_encomenda_do_mesmo_tenant_fk`.
        self.assertEqual(len(linhas), 92)
        for nome, alvo in linhas:
            with self.subTest(fk=nome):
                self.assertTrue(alvo.startswith("platform."), alvo)


class TestPapeis(ComBase):
    """CA 6: os tres papeis existem, e `kamba_app` nao cria tabelas."""

    def atributos(self) -> dict[str, tuple]:
        linhas = self.consultar(
            "SELECT rolname, rolsuper, rolcreatedb, rolcreaterole, rolbypassrls, "
            "rolcanlogin, rolreplication FROM pg_roles WHERE rolname LIKE 'kamba\\_%%'"
        )
        return {linha[0]: linha[1:] for linha in linhas}

    def test_existem_os_nove_e_so_os_nove(self) -> None:
        """Os tres do KAM-003, o `kamba_resolver` do KAM-004, o `kamba_identity`
        do KAM-008, o `kamba_audit` do KAM-012, o `kamba_agr` do KAM-026 e o
        `kamba_pay_hooks` do KAM-053.

        **O nome deste teste mudou de «sete» para «oito», e nao se tirou o
        numero.** A licao que o KAM-027 escreveu para as listas literais — um
        numero no nome transforma a invariante «as excepcoes sao as declaradas»
        em «as excepcoes sao tres» — vale para uma lista de **excepcoes**, que
        cresce quando alguem tem razao para a fazer crescer. Aqui a lista nao e
        de excepcoes: e o conjunto dos papeis da plataforma, e o numero **e** a
        afirmacao. Um papel novo nao e um caso particular de nada; e um sujeito
        novo na matriz de privilegios, e quem o acrescenta renomeia este teste
        de proposito, porque e isso que obriga a olhar para as oito linhas que
        passam a existir em cada tabela.

        O `kamba_pay_hooks` existe por uma razao de **ordem** e nao de
        conveniencia: resolve `webhook_token -> account` antes de existir
        contexto de tenant, porque no instante em que um callback chega ainda
        nao se sabe de quem ele e (`docs/tecnica/04` secao 5.1). Ver o
        `db/bootstrap.py` para os atributos e o `ESPERADO_POR_TABELA` de
        `test_privilegios.py` para o que ele alcanca — que e o inbox, sem
        `tenant_id`, e sete colunas da `payment_accounts`, e nada mais.

        **O nono e o `kamba_pay` do KAM-197**, por decisao (A) do fundador
        de 2026-11-13: o consumidor do PAY, o unico com `EXECUTE` na porta
        que abre a `refund_cases`. Existe para que a tabela tenha um so dono
        **imposto pela base** — o COM corre como `kamba_app`, e uma porta
        concedida ao `kamba_app` deixava o COM abrir casos.
        """
        self.assertEqual(
            set(self.atributos()),
            {"kamba_migrator", "kamba_app", "kamba_batch", "kamba_resolver",
             "kamba_identity", "kamba_audit", "kamba_agr", "kamba_pay_hooks",
             "kamba_pay"},
        )

    def test_nenhum_e_superutilizador_nem_cria_bases_ou_papeis(self) -> None:
        for papel, (super_, createdb, createrole, _, login, replicacao) in (
            self.atributos().items()
        ):
            with self.subTest(papel=papel):
                self.assertFalse(super_)
                self.assertFalse(createdb)
                self.assertFalse(createrole)
                self.assertFalse(replicacao)
                self.assertTrue(login)

    def test_so_o_batch_contorna_a_rls(self) -> None:
        contorna = {papel: a[3] for papel, a in self.atributos().items()}
        self.assertEqual(
            contorna,
            {
                "kamba_migrator": False,
                "kamba_app": False,
                "kamba_batch": True,
                "kamba_resolver": False,
                "kamba_identity": False,
                # KAM-012: quem audita um tenant audita **esse** tenant. A
                # cadeia de plataforma le-se com o `kamba_batch`.
                "kamba_audit": False,
                # KAM-026: as tabelas do `lg` nao tem politica de RLS, pelo que
                # nao ha nada para contornar. O que isola o checkpointer e nao
                # ter `USAGE` no `platform` — revisao `0020`.
                "kamba_agr": False,
                # KAM-053: **`NOBYPASSRLS`, e isso parece contradizer a razao
                # pela qual ele existe — nao contradiz.** Ele resolve o
                # `webhook_token` antes de haver contexto de tenant, e a
                # tentacao era dar-lhe `BYPASSRLS` para que o `SELECT` na
                # `payment_accounts` (RLS `FORCE`) nao devolvesse zero linhas.
                # Resolveu-se de outra forma e mais estreita: a politica
                # `pay_hooks_token`, **por papel**, mais um `GRANT` de sete
                # colunas que nao inclui o `credenciais_ref` nem o
                # `manual_instrucoes`. Com `BYPASSRLS` ele via as cobrancas e o
                # ledger de todos os tenants; assim ve sete colunas das contas e
                # o inbox, que nao tem `tenant_id`.
                "kamba_pay_hooks": False,
                # KAM-197: o consumo trabalha um tenant de cada vez, com o
                # `app.tenant_id` do envelope, e a porta le a encomenda sob
                # RLS. Com `BYPASSRLS` abria casos em qualquer tenant.
                "kamba_pay": False,
            },
        )

    def test_create_table_sob_kamba_app_falha(self) -> None:
        cursor = self.ligar("app").cursor()
        for schema in ("platform", "public"):
            with self.subTest(schema=schema):
                self.assertErroSql(
                    PRIVILEGIO_INSUFICIENTE,
                    cursor,
                    f"CREATE TABLE {schema}.nao_devia_existir (x integer)",
                )

    def test_kamba_app_nao_altera_nem_apaga_tabelas(self) -> None:
        cursor = self.ligar("app").cursor()
        for instrucao in (
            "ALTER TABLE platform.tenants ADD COLUMN intrusa text",
            "DROP TABLE platform.entitlements",
            "CREATE SCHEMA nao_devia_existir",
            "TRUNCATE platform.entitlements",
        ):
            with self.subTest(instrucao=instrucao):
                self.assertErroSql(PRIVILEGIO_INSUFICIENTE, cursor, instrucao)

    def test_kamba_batch_tambem_nao_faz_ddl(self) -> None:
        """`BYPASSRLS` e sobre linhas, nao sobre estrutura."""
        cursor = self.ligar("batch").cursor()
        self.assertErroSql(
            PRIVILEGIO_INSUFICIENTE,
            cursor,
            "CREATE TABLE platform.nao_devia_existir (x integer)",
        )

    def test_app_e_batch_leem_e_escrevem_o_que_lhes_cabe(self) -> None:
        """E o que lhes cabe deixou de ser o mesmo nas tres tabelas (KAM-009).

        A revisao `0007` tirou a `kamba_app` o `INSERT` em `entitlements` e o
        `UPDATE` sobre `tenants.estado`: escrever entitlements e mexer no
        estado do tenant sao de retaguarda, e a revisao adversarial mostrou o
        que acontecia enquanto nao eram — um tenant criava o proprio tecto e
        reactivava-se a si proprio. O que esta aqui passou a ser o que cada
        papel ainda **faz**; o que nenhum deles faz esta em
        `tests/test_privilegios.py` e em `tests_ten/test_escalada.py`.
        """
        for identidade in ("app", "batch"):
            with self.subTest(identidade=identidade):
                cursor = self.ligar(identidade).cursor()
                tenant = factories.tenant(cursor)
                factories.canal(cursor, tenant)
                cursor.execute(
                    "UPDATE platform.tenants SET nome = 'Outro nome' WHERE id = %s",
                    (tenant,),
                )
                cursor.execute(
                    "SELECT count(*) FROM platform.tenant_channels WHERE tenant_id = %s",
                    (tenant,),
                )
                self.assertEqual(cursor.fetchone()[0], 1)

    def test_so_o_batch_escreve_entitlements(self) -> None:
        """A outra metade do teste acima, desde o KAM-009."""
        cursor = self.ligar("batch").cursor()
        tenant = factories.tenant(cursor)
        factories.entitlement(cursor, tenant, limites={"msgs_ai_mes": 10})
        # `suspenso` e nao `ativo` desde a revisao 0040 (KAM-090): o que este
        # ensaio afirma e que o lote muda o `estado`, e `ativo` passou a exigir
        # o aceite dos quatro documentos, que o lote nao pode gravar (nao tem
        # `INSERT` em `contract_acceptance`) e que uma ligacao que nunca
        # confirma nao lhe consegue mostrar. O gate tem ensaio proprio, com
        # este mesmo papel, em `test_contratos_schema.py`.
        cursor.execute(
            "UPDATE platform.tenants SET estado = 'suspenso' WHERE id = %s", (tenant,)
        )
        cursor.execute(
            "SELECT count(*) FROM platform.entitlements WHERE tenant_id = %s", (tenant,)
        )
        self.assertEqual(cursor.fetchone()[0], 1)

    def test_o_migrator_nao_e_dono_de_nada_fora_do_que_criou(self) -> None:
        linhas = self.consultar(
            "SELECT schemaname, tablename FROM pg_tables "
            "WHERE tableowner = 'kamba_migrator' ORDER BY 1, 2"
        )
        self.assertEqual(
            linhas,
            # O `lg` entra aqui porque e o `kamba_migrator` que o cria, como
            # cria o `platform` (KAM-026, revisao `0020`). O `ORDER BY 1, 2` da
            # consulta ordena por esquema, e `lg` vem antes de `platform`.
            #
            # O `dat` entra pela mesma razao (KAM-030, revisao `0023`) e vem
            # **antes** do `lg`, que e o que aquele `ORDER BY` manda.
            #
            # O `servicos` entra pela mesma razao (KAM-047, revisao `0025`) e vem
            # **depois** do `public`: a ordem e alfabetica pelo esquema, e
            # `public` < `servicos`. E a primeira vez que alguma coisa fica
            # depois da `alembic_version` nesta lista.
            #
            # O `idx` entra pela mesma razao (KAM-061, revisao `0045`) e vem
            # **entre** o `dat` e o `lg`: `dat` < `idx` < `lg`.
            [("dat", tabela) for tabela in TABELAS_DAT]
            + [("idx", tabela) for tabela in TABELAS_IDX]
            + [("lg", tabela) for tabela in TABELAS_LG]
            + [("platform", tabela) for tabela in TABELAS]
            + [("public", "alembic_version")]
            + [("servicos", tabela) for tabela in TABELAS_SERVICOS],
        )

    def test_public_nao_tem_create_no_schema_public(self) -> None:
        linhas = self.consultar(
            "SELECT has_schema_privilege('public', 'public', 'CREATE'), "
            "has_schema_privilege('kamba_app', 'platform', 'CREATE'), "
            "has_schema_privilege('kamba_app', 'platform', 'USAGE')"
        )
        self.assertEqual(linhas, [(False, False, True)])
