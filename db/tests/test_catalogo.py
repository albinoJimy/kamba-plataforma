"""Gate 8: o que o catalogo do PostgreSQL diz, e nao o que o DDL parece dizer.

Criterios de aceitacao 5 e 6 do KAM-003, e as linhas de isolamento e
privacidade do DoD.
"""

from __future__ import annotations

from tests import factories
from tests.base import (
    PRIVILEGIO_INSUFICIENTE,
    TABELAS,
    TABELAS_DAT,
    TABELAS_LG,
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
        por_identidade = {"events_outbox", "events_dlq", "audit_log", "tool_audit"}
        linhas = self.consultar(
            "SELECT table_name, data_type, column_default FROM information_schema.columns "
            "WHERE table_schema = 'platform' AND column_name = 'id'"
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
        isso o dicionario §2 manda `uuid`. Sao **quatro** as excepcoes, e as
        quatro tem a mesma propriedade: nenhum papel sujeito a RLS le a coluna.
        O outbox porque a tabela nao e exposta a nenhum tenant e a ordem e o que
        o publicador precisa; a `events_dlq` porque `kamba_app` tem so `INSERT`
        nela e quem a le e a operacao (KAM-006, §6.4); a `audit_log`
        (KAM-012) pela mesma razao com mais forca — o `kamba_app` **escreve e
        nao le**, e a ordem de insercao e o que torna a cadeia de hash
        verificavel por quem a le de cima a baixo; e a `tool_audit` (KAM-028)
        pela razao da `audit_log`, com a cobertura do critero 5 em vez da
        cadeia.

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
            [("audit_log", "id", "a"), ("events_dlq", "id", "a"),
             ("events_outbox", "id", "a"), ("tool_audit", "id", "a")],
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
                ("consent_event", "id", "uuid", "gen_random_uuid()"),
                ("consent_texts", "purpose", "text", None),
                ("consent_texts", "version", "text", None),
                ("contact_deks", "dek_id", "uuid", "gen_random_uuid()"),
                ("contact_endpoints", "id", "uuid", "gen_random_uuid()"),
                ("contacts", "contact_id", "uuid", "gen_random_uuid()"),
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
                ("entitlements", "modulo", "text", None),
                ("entitlements", "tenant_id", "uuid", None),
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
                ("outbound_messages", "id", "uuid", "gen_random_uuid()"),
                ("owner_contacts", "id", "uuid", "gen_random_uuid()"),
                ("owner_notices", "id", "uuid", "gen_random_uuid()"),
                ("tenant_channels", "id", "uuid", "gen_random_uuid()"),
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

    #: As unicas tabelas com `tenant_id` **anulavel**, e a razao (KAM-012).
    #:
    #: Uma accao de plataforma — `batch.run`, `breakglass.open` — nao tem
    #: tenant, e inventar-lhe um era pior: punha prova de operacao dentro da
    #: cadeia de um cliente. O `tenant_id` nulo e invisivel a politica
    #: `tenant_iso` para toda a gente, e quem escreve e le essas linhas e o
    #: `kamba_batch`, que tem `BYPASSRLS`. **Nao e um furo no isolamento: e o
    #: isolamento a funcionar** — o papel da aplicacao nao consegue escrever
    #: uma accao de plataforma nem ve que ela existe.
    ANULAVEIS = frozenset({"audit_log", "audit_heads"})

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
             # KAM-012. As duas da auditoria, e sao as **unicas** com
             # `tenant_id` anulavel em todo o schema — ver `ANULAVEIS` logo
             # abaixo e a razao que la esta escrita.
             "audit_log", "audit_heads",
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
             "tool_idempotency"},
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

    def test_nao_ha_colunas_de_dinheiro_nem_saldos(self) -> None:
        """DoD: o DDL nao modela saldos — a plataforma nao detem fundos."""
        linhas = self.consultar(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema = 'platform' AND (column_name LIKE '%%saldo%%' "
            " OR column_name LIKE '%%balance%%' OR column_name LIKE '%%\\_minor' "
            " OR column_name LIKE '%%\\_kz')"
        )
        self.assertEqual(linhas, [])

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
        self.assertEqual(len(linhas), 40)
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

    def test_existem_os_sete_e_so_os_sete(self) -> None:
        """Os tres do KAM-003, o `kamba_resolver` do KAM-004, o `kamba_identity`
        do KAM-008, o `kamba_audit` do KAM-012 e o `kamba_agr` do KAM-026."""
        self.assertEqual(
            set(self.atributos()),
            {"kamba_migrator", "kamba_app", "kamba_batch", "kamba_resolver",
             "kamba_identity", "kamba_audit", "kamba_agr"},
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
        cursor.execute(
            "UPDATE platform.tenants SET estado = 'ativo' WHERE id = %s", (tenant,)
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
            [("dat", tabela) for tabela in TABELAS_DAT]
            + [("lg", tabela) for tabela in TABELAS_LG]
            + [("platform", tabela) for tabela in TABELAS]
            + [("public", "alembic_version")],
        )

    def test_public_nao_tem_create_no_schema_public(self) -> None:
        linhas = self.consultar(
            "SELECT has_schema_privilege('public', 'public', 'CREATE'), "
            "has_schema_privilege('kamba_app', 'platform', 'CREATE'), "
            "has_schema_privilege('kamba_app', 'platform', 'USAGE')"
        )
        self.assertEqual(linhas, [(False, False, True)])
