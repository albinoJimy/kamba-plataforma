"""Base comum dos testes do gate 8.

Estes testes sao **destrutivos**: fazem `downgrade base`, que apaga o schema
`platform`. Por isso ha um trinco, e ele nao e opcional:

    a base tem de se chamar exactamente `kamba_gate8`.

`db/gate_bd.py` cria uma base com esse nome num PostgreSQL descartavel. Apontar
estes testes a `kamba_platform` — por engano num `.env`, por uma variavel
herdada da shell — faz a suite recusar-se a correr em vez de apagar a base de
desenvolvimento.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

import bootstrap
import ligacao

DB = Path(__file__).resolve().parents[1]
BASE_DESCARTAVEL = "kamba_gate8"

#: O que a revisao 0001 cria em `platform`.
TABELAS_0001 = ("entitlements", "tenant_channels", "tenants")

#: O que a revisao 0003 (KAM-008) acrescenta: identidade de contacto.
TABELAS_0003 = ("contact_deks", "contact_endpoints", "contacts", "hmac_key_versions")

#: O que a revisao 0004 (KAM-005) acrescenta: outbox, sequencia por agregado,
#: subscricoes e o arquivo de eventos. O `events_log_default` esta aqui porque
#: o `pg_tables` lista a particao (`relkind` 'r') ao lado da particionada
#: ('p'): sao duas linhas do catalogo, e a lista e do catalogo.
TABELAS_0004 = (
    "events_log",
    "events_log_default",
    "events_outbox",
    "evt_agregado_seq",
    "evt_subscricoes",
)

#: As quatro tabelas do consumo idempotente (KAM-006, revisao 0005).
TABELAS_0005 = (
    "events_consumed",
    "events_dlq",
    "evt_acoes",
    "evt_dlq_aprovacoes",
)

#: Tudo o que existe em `platform` em `head`, por ordem alfabetica. Lista
#: fechada: uma tabela a mais (encomendas, pagamentos, consumidores) e escopo de
#: outro ticket, e entra aqui pela mao de quem a criar.
#: O que a revisao 0006 (KAM-012) acrescenta: o registo de auditoria e a
#: cabeca da cadeia de hash de cada tenant.
TABELAS_0006 = ("audit_heads", "audit_log")

#: O que a revisao 0007 (KAM-009) acrescenta: o contador de uso por periodo e
#: o livro que torna o consumo idempotente.
TABELAS_0007 = ("tenant_usage", "usage_ledger")

#: O que a revisao 0008 (KAM-013) acrescenta: o registo dos webhooks da Meta
#: que chegaram, e a quarentena dos que nao se conseguiu encaminhar.
#:
#: Sao as duas unicas tabelas de `platform` **sem `tenant_id`** fora das de
#: referencia: o GWY e o endpoint unico da Meta e o tenant so nasce no CHR
#: (KAM-014). A revisao `0008` escreve a razao, e por isso tambem nao ha
#: entrada em `ci/rls_exceptions.yaml` — o teste X-05 descobre as tabelas a
#: isolar **pela coluna `tenant_id`**, que estas nao tem.
TABELAS_0008 = ("inbound_events", "unrouted_events")

#: O que a revisao 0009 (KAM-014) acrescenta: a conversa entre um contacto e um
#: canal.
#:
#: E a **primeira** tabela do caminho do webhook com `tenant_id` — o tenant
#: nasce no CHR, que corre depois da escrita das duas de cima —, e por isso a
#: primeira que o teste X-05 do gate 6 descobre pela coluna e a primeira com
#: politica `tenant_iso`.
TABELAS_0009 = ("conversations",)

#: O que a revisao 0010 (KAM-015) acrescenta: a saida de canal.
#:
#: Duas, e a ordem de criacao importa — a `outbound_messages` referencia a
#: `conversations` da `0009` e a `message_templates` nao referencia nenhuma das
#: duas. No `downgrade` cai a de envios primeiro, por isso.
TABELAS_0010 = ("message_templates", "outbound_messages")

#: O que a revisao 0011 (KAM-019) acrescenta: a passagem a humano.
#:
#: Duas, e a ordem de criacao importa — a `handoffs` referencia a
#: `conversations` da `0009` por FK composta, e a `handoff_accounts` nao
#: referencia nenhuma das duas. No `downgrade` caem pela ordem inversa da
#: criacao.
TABELAS_0011 = ("handoff_accounts", "handoffs")

#: O que a revisao 0012 (KAM-020) acrescenta: a midia recebida.
#:
#: Uma so, e referencia **tres** tabelas por FK: a `tenants` da `0001`, e a
#: `contacts` da `0003` e a `conversations` da `0009`, as duas por FK composta
#: com o `tenant_id`. **Nao e a tabela com mais FK do esquema** — a
#: `outbound_messages` da `0010` tem quatro —, e a primeira versao desta nota
#: dizia que era. A razao de serem tres e que uma linha dela so faz sentido
#: dentro de uma conversa de um contacto de uma PME.
TABELAS_0012 = ("media_assets",)

#: A `0013` nao criou tabela nenhuma: acrescentou duas colunas a
#: `tenant_channels`. Fica declarada vazia e nao omitida, para que quem contar
#: as revisoes aqui nao conclua que uma se perdeu.
TABELAS_0013: tuple[str, ...] = ()

#: KAM-021: o registo das transicoes de qualidade do canal.
TABELAS_0014 = ("channel_quality_log",)

#: KAM-022: a prova de consentimento e o texto do aviso.
#:
#: **Duas tabelas e uma vista**, e a vista **nao** entra aqui: a descoberta do
#: catalogo le `pg_class` com `relkind IN ('r', 'p')` e uma vista e `'v'`. Fica
#: dito porque e a primeira vista do esquema e porque quem conte as relacoes de
#: `platform` passa a encontrar uma a mais do que as tabelas desta tupla.
#:
#: A `consent_texts` nao tem `tenant_id` — e um texto juridico de plataforma e
#: nao dado de tenant —, pelo que **nao** entra no X-05 nem no
#: `ci/rls_exceptions.yaml`: o gate 6 pergunta por RLS as tabelas que tem a
#: coluna. Entra nesta tupla porque existe em `platform`.
TABELAS_0015 = ("consent_event", "consent_texts")

#: KAM-016: a tentativa de onboarding de canal pelo Embedded Signup v4.
#:
#: **E a `0017` e nao a `0016`**: o KAM-018 reclamou aquele numero e a
#: revisao dele chegou primeiro ao remoto. A razao esta no docstring da
#: propria revisao.
#:
#: Uma so, e **nao acrescenta coluna nenhuma a `tenant_channels`** — os tres
#: identificadores que o criterio 8 manda guardar (`waba_id`, `waac_id`,
#: `phone_number_id`) existem desde a `0001`, com o `token_ref`. Referencia duas
#: tabelas por FK: a `tenants` da `0001` e a propria `tenant_channels`, esta por
#: FK composta com o `tenant_id` — que assenta na `tenant_channels_tenant_id_uq`
#: que a `0009` acrescentou precisamente para isto.
TABELAS_0017 = ("channel_onboarding",)

#: KAM-017: o estado de coexistencia de um canal (revisao `0018`).
#:
#: Uma so, e **nao acrescenta coluna nenhuma a `tenant_channels`** — o
#: `coexistence_synced_at` e o `last_account_update_at` existem desde a `0001` e
#: nunca tiveram escritor; este ticket e o primeiro, e isso custa codigo e nao
#: DDL. Referencia duas tabelas por FK: a `tenants` da `0001` e a propria
#: `tenant_channels`, esta por FK composta com o `tenant_id` — que assenta na
#: `tenant_channels_tenant_id_uq` que a `0009` acrescentou para isto.
TABELAS_0018 = ("channel_coexistence",)

#: KAM-115: o contacto alternativo do dono e o registo dos avisos (revisao `0019`).
#:
#: **Duas, e e a primeira revisao do epic a criar duas tabelas de negocio.** Sao
#: duas e nao uma porque o criterio 7 manda marcar o **contacto** como invalido
#: quando uma entrega falha: com uma tabela so, a invalidacao vivia na ultima
#: linha de aviso e a pergunta «este dono tem contacto valido?» passava a ser uma
#: consulta sobre o historico de envios em vez de um facto.
#:
#: As duas referenciam **so** a `tenants` da `0001`, e nenhuma aponta para a
#: outra — e por isso que a ordem entre elas e arbitraria. Nenhuma toca em
#: `tenant_channels`: o aviso e do **dono** e nao do canal, e o canal identifica-se
#: no `episodio`, que e texto opaco.
TABELAS_0019 = ("owner_contacts", "owner_notices")

#: KAM-026: as duas tabelas do checkpointer (revisao `0020`).
#:
#: **Noutro esquema, e por isso numa constante propria.** Todas as tuplas acima
#: sao nomes de tabela do `platform` e o `TABELAS` junta-as sem qualificar; estas
#: vivem no `lg` e um nome solto misturado la dentro fazia o catalogo procura-las
#: no sitio errado. Quem as consome diz o esquema.
TABELAS_LG = ("checkpoint_writes", "checkpoints")

#: KAM-030: as do esquema `dat` (revisao `0023`). Constante propria pela mesma
#: razao do `TABELAS_LG`, acima — vivem noutro esquema e quem as consome diz
#: qual.
#:
#: **Sao duas e a segunda e uma particao.** A `llm_call_log_default` e a unica
#: que a revisao cria, e aparece no catalogo como tabela: o
#: `test_o_migrator_nao_e_dono_de_nada_fora_do_que_criou` conta-a, e o X-05 do
#: *gate* 6 exige-lhe RLS `FORCE` por si. As mensais nascem do *job* da
#: retencao (KAM-071) e **nao** entram aqui: esta lista e o que a cadeia de
#: revisoes cria.
TABELAS_DAT = ("llm_call_log", "llm_call_log_default")

#: As do `dat` que a **matriz de privilegios** cobre. A particao fica de fora, e
#: por uma razao e nao por esquecimento: os `GRANT` da revisao `0023` sao todos
#: no **pai**, pelo que a particao nao tem privilegio proprio nenhum — e e isso
#: que o `verificar_particoes` do *gate* 6 exige dela. Uma linha de matriz para
#: uma relacao sem privilegios era uma matriz de zeros a afirmar o que o *gate* 6
#: ja afirma.
TABELAS_DAT_COM_MATRIZ = ("llm_call_log",)

#: KAM-047: as do esquema `servicos` (revisao `0025`). Constante propria pela
#: mesma razao do `TABELAS_LG` e do `TABELAS_DAT` — vivem noutro esquema e quem
#: as consome diz qual.
#:
#: **Sao quatro, e nenhuma e particao.** Por ordem alfabetica, que e a que o
#: `ORDER BY 1, 2` do `test_o_migrator_nao_e_dono_de_nada_fora_do_que_criou`
#: espera dentro de um esquema. O esquema vem **depois** do `platform` nessa
#: consulta: `dat` < `lg` < `platform` < `public` < `servicos`.
TABELAS_SERVICOS = ("availability_rules", "bookings", "resources", "services")

#: As do `servicos` que a **matriz de privilegios** cobre: as quatro.
#:
#: Ao contrario do `dat`, aqui nao fica nenhuma de fora — e a razao e a
#: diferenca entre os dois esquemas. No `dat` a particao nao tem privilegio
#: proprio nenhum (os `GRANT` da `0023` sao todos no pai), e uma linha de matriz
#: de zeros afirmava o que o *gate* 6 ja afirma. No `servicos` as quatro tem
#: privilegios concedidos **por tabela**, e tres delas tem conjuntos
#: **diferentes**: o catalogo e so de leitura para a aplicacao, a `bookings` e
#: de leitura e escrita, e o `UPDATE` dela e por coluna.
TABELAS_SERVICOS_COM_MATRIZ = TABELAS_SERVICOS
#: As vistas do esquema. Separadas das tabelas porque a descoberta do catalogo
#: tambem as separa, e porque o `verificar_vistas` do
#: `db/tests_isolamento/catalogo.py` — que existe desde o KAM-004 — tem aqui o
#: que ver: `security_invoker = true` em **todas**.
#:
#: A `consent_actual` e do KAM-022 e foi a primeira. A `v_draft_metrics` e do
#: KAM-114 (revisao `0024`) e e a segunda: ela existe porque nem o `tenant_id`
#: nem o `graph_version` podem ser etiqueta de metrica (a gramatica do
#: `kamba_core.ten.metricas` recusa os dois pela forma) **e** porque esta
#: biblioteca nao tem histogramas — um p50 nao e exprimivel nela. A
#: desagregacao faz-se nas colunas e le-se aqui.
#:
#: A `v_transfer_audit` e do KAM-069 (revisao `0036`) e e a quinta: junta
#: `dat.llm_call_log` a `platform.tenant_destinations` e enumera **violacoes** —
#: as chamadas que sairam sem destino autorizado com `apd_ref` no instante em
#: que sairam. O alvo do criterio 7 e zero linhas, e e por isso que lista o que
#: esta mal e nao o que esta bem: uma vista que listasse conformidades nunca se
#: lia. **E a primeira que atravessa esquemas**, o que com `security_invoker`
#: tem uma consequencia: quem a le precisa de privilegio nas duas tabelas, e o
#: `kamba_audit` — que nao tem `BYPASSRLS` — ve o tenant do seu contexto e nao
#: a plataforma toda.
#:
#: As duas do KAM-053 (revisao `0029`) sao a terceira e a quarta, e nascem com
#: `security_invoker = true` como as outras — para vistas nao ha lista de
#: excepcoes. A `v_payment_events_audit` expoe o predicado de HMAC do
#: `docs/tecnica/08` secao 14 como expressao derivada; a
#: `v_payment_ledger_heads` e a cabeca da cadeia de *hashes* por cobranca, que
#: o *job* diario exporta para STO como ancora externa.
#:
#: A `v_oferta_viva` e do KAM-051 (revisao `0037`) e e a sexta: e o contrato de
#: leitura da oferta viva que a tool `search_products` junta aos candidatos do
#: indice (`docs/tecnica/05` secao 6.3). Sao **nove** colunas: seis projectadas
#: da `offer_terms` e tres que sao decisao — o `product_ref` (que **e** o `sku`,
#: com o *join* a cair no `offer_terms_pkey`), o `publicado` (predicado exposto e
#: nao aplicado) e o `lido_em`. A conta das dezesseis colunas da tabela de origem
#: esta no comentario do `INVENTARIO["v_oferta_viva"]`. **Sem coluna de nivel de
#: stock:** o criterio 7 esta bloqueado pelo D3 e pelo KAM-045.
#:
#: **Por ordem alfabetica**, que e a que o `_vistas` devolve.
VISTAS = (
    "consent_actual",
    "v_draft_metrics",
    "v_oferta_viva",
    "v_payment_events_audit",
    "v_payment_ledger_heads",
    "v_transfer_audit",
)

#: KAM-028: o registo de invocacoes da ToolLayer (revisao `0021`).
#:
#: **Uma tabela, no `platform` e nao no `lg`.** O `docs/tecnica/02` §6.4 poe-a
#: ao lado da `audit_log` e nao junto do *checkpointer*: e um registo de
#: auditoria da plataforma, lido por quem audita, e o papel que escreve o `lg`
#: nao tem `USAGE` no `platform` (KAM-026).
TABELAS_0021 = ("tool_audit",)

#: KAM-029: a barreira de idempotencia das tools de escrita (revisao `0022`).
#:
#: **Uma tabela, no `platform`, e ao contrario da `0021` nao e *append-only*.**
#: O protocolo do `docs/tecnica/02` §6.3 e `INSERT` com estado `em_curso` ->
#: executar -> `UPDATE` com o resultado, e um *trigger* de imutabilidade recusava
#: o segundo passo; o que a protege e o `UPDATE` concedido **por coluna**. E a
#: razao pela qual ela, ao contrario da `tool_audit`, tem receita de sementes no
#: `db/tests_isolamento/sementes.py`: apaga-se com `DELETE`.
TABELAS_0022 = ("tool_idempotency",)

#: O que a revisao 0024 (KAM-114) acrescenta: as decisoes do modo concierge.
#:
#: **A `v_draft_metrics` nao entra aqui**: e uma **vista**, e o `pg_tables` que
#: alimenta esta lista nao lista vistas (`relkind` 'v'). Quem a verifica e o
#: `verificar_vistas` do *gate* 6, que exige `security_invoker` em todas.
TABELAS_0024 = ("draft_decisions",)

#: KAM-052: a conta de pagamento com beneficiario explicito (revisao `0027`).
#:
#: **Uma tabela, no `platform`, e a primeira do esquema com `tenant_id`
#: anulavel que guarda dados de tenant.** Nula se e so se
#: `beneficiary_kind = 'plataforma_receita_propria'` — a conta com que a
#: KAMBA cobra a propria assinatura (`docs/tecnica/04` secao 11.2), que
#: existe para nao activar o tenant `platform`, vedado por D2. A
#: equivalencia esta no `CHECK`, pelo que uma conta de PME **nunca** tem
#: `tenant_id` nulo. Entra no `ANULAVEIS` de `test_catalogo.py` com a razao;
#: decisao do fundador, 2026-10-29.
#:
#: A `payment_charges` e a `payment_events` **nao** estao aqui: a ordem do
#: `docs/tecnica/04` secao 6 e `orders_mirror -> payment_accounts ->
#: payment_charges -> payment_events`, e a `0027` entrega a segunda. As duas
#: nascem na `0029` (KAM-053) — ver `TABELAS_0029` —, e a `orders_mirror`
#: continua a faltar: e do KAM-044.
TABELAS_0027 = ("payment_accounts",)

#: O que a revisao 0028 (KAM-043) acrescenta: os termos comerciais de um SKU e
#: a cotacao do dono — o preco opaco e o stock nao-garantido.
#:
#: Duas, e nenhuma referencia a outra: a `offer_terms` referencia so a
#: `tenants` da `0001`, e a `price_quotes` referencia a `tenants` e a
#: `contacts` da `0003`, esta por FK **composta** com o `tenant_id` (a
#: correccao de 2026-10-27 do `docs/tecnica/03` secao 5.4). E por isso que a
#: revisao pode vir antes da `orders_mirror`, que e do **KAM-044**.
#:
#: A `offer_terms` e a primeira tabela do esquema com **chave primaria
#: composta** — `(tenant_id, sku)` —, e nao e estilo: e o que faz da colisao de
#: SKU entre tenants (ISO-33..38) um nao-problema por construcao.
TABELAS_0028 = ("offer_terms", "price_quotes")

#: O que a revisao 0029 (KAM-053) acrescenta: o ledger de pagamentos.
#:
#: **Quatro — tantas como as da `0005`, e so a `0004` trouxe mais** (cinco, e
#: uma delas e particao). A primeira versao desta nota escrevia «a revisao que
#: traz mais tabelas de uma vez», e era falso: conta-se nas tuplas acima.
#: Por ordem alfabetica, que e a do `pg_tables ORDER BY 1` desta lista — e nao
#: a de criacao, que e `payment_charges -> payment_callbacks_inbox ->
#: payment_events -> payment_outbox_map` (a ordem das FK: o ledger referencia a
#: cobranca).
#:
#: **Duas delas nao tem `tenant_id`, e isso e desenho e nao lapso.** A
#: `payment_callbacks_inbox` guarda a entrega HTTP **antes** de se saber de quem
#: ela e (`docs/tecnica/04` secao 5.1): uma coluna de isolamento preenchida
#: depois era uma chave que o atacante controla no instante em que e escrita, e
#: o que a isola e o papel estreito `kamba_pay_hooks`. A `payment_outbox_map` e
#: configuracao **global**, como a `evt_subscricoes` da `0004`. Nenhuma das duas
#: entra no X-05 do *gate* 6 nem em `ci/rls_exceptions.yaml`: a descoberta
#: pergunta pela coluna, e elas nao a tem.
#:
#: As outras duas — `payment_charges` e `payment_events` — tem `tenant_id
#: NOT NULL`, RLS `FORCE` e politica `tenant_iso`, e entram no X-05 sozinhas.
TABELAS_0029 = (
    "payment_callbacks_inbox",
    "payment_charges",
    "payment_events",
    "payment_outbox_map",
)

#: O que a revisao 0030 (KAM-044) acrescenta: as encomendas.
#:
#: **Cinco — e a revisao que traz mais tabelas de uma vez.** As quatro de
#: `docs/tecnica/03` secao 5.4 que faltavam (`orders_mirror`, `order_intents`,
#: `order_state_log` e, fora daquele bloco, o `order_reconciliation_issues` dos
#: Detalhes Tecnicos do bloco) mais o `order_state_graph`, que o secao 6.2 manda
#: existir como **dados**. Por ordem alfabetica, que e a do `pg_tables ORDER BY
#: 1` desta lista — e nao a de criacao, que e `orders_mirror ->
#: order_intents -> order_state_log -> order_state_graph ->
#: order_reconciliation_issues` (a ordem das FK: as tres ultimas referenciam a
#: primeira).
#:
#: A `stock_reservations` do mesmo bloco SQL **nao** esta aqui: e do KAM-045, e
#: entra no `TABELAS_0033` abaixo.
#:
#: **Uma delas nao tem `tenant_id`, e isso e desenho e nao lapso.** O
#: `order_state_graph` e tabela de **referencia**, como a `evt_subscricoes` da
#: `0004` e a `payment_outbox_map` da `0029`: as transicoes validas de um
#: sistema nao sao configuracao de tenant, e quem lhe escreve e uma revisao. Nao
#: entra no X-05 do *gate* 6 nem em `ci/rls_exceptions.yaml` — a descoberta
#: pergunta pela coluna, e ela nao a tem.
TABELAS_0030 = (
    "order_intents",
    "order_reconciliation_issues",
    "order_state_graph",
    "order_state_log",
    "orders_mirror",
)

#: O que a revisao 0032 (KAM-054) acrescenta: a confirmacao humana auditada.
#:
#: **Quatro, as do `docs/tecnica/04` secao 6.2-6.3 que faltavam.** Por ordem
#: alfabetica, que e a do `pg_tables ORDER BY 1` desta lista — e nao a de
#: criacao, que e `payment_confirmers -> manual_confirmations -> refund_cases
#: -> fraud_signals` (a ordem das FK: as tres ultimas referenciam a
#: `payment_charges` da `0029` e as duas primeiras a `contacts` da `0003`).
#:
#: **As quatro tem `tenant_id NOT NULL`**, RLS `FORCE` e politica `tenant_iso`,
#: e entram no X-05 do *gate* 6 sem ninguem as declarar — ao contrario das duas
#: da `0029` e da `order_state_graph` da `0030`, que nao tem a coluna. Nenhuma
#: entra em `ci/rls_exceptions.yaml`, que esta vazio e deve continuar vazio.
TABELAS_0032 = (
    "fraud_signals",
    "manual_confirmations",
    "payment_confirmers",
    "refund_cases",
)

#: O que a revisao 0033 (KAM-045) acrescenta: a reserva de stock.
#:
#: **Uma**, a `platform.stock_reservations` do mesmo bloco SQL do
#: `docs/tecnica/03` secao 5.4 que a `0030` deixou com o credor escrito. As duas
#: colunas de quantidade que a mesma revisao acrescenta vivem na `offer_terms`,
#: que e da `0028` e ja esta na lista dela — o inventario coluna a coluna de
#: `test_inventario.py` e que as conta.
TABELAS_0033 = ("stock_reservations",)

#: O que a revisao 0034 (KAM-091) acrescenta: o estado da saga de provisioning.
#:
#: **Uma**, a `platform.provisioning_step`. Chega depois do codigo dela, que
#: fundiu sem a tabela porque a cadeia e linear e a `0033` ainda nao estava em
#: `main`; a caixa da DoD do KAM-091 ficou vazia com o credor escrito.
#:
#: **Tem `tenant_id NOT NULL`** — pre-alocado, e **sem FK** para `tenants`,
#: porque e o passo 1 da saga que escreve essa linha —, RLS `FORCE` e politica
#: `tenant_iso`, e entra no X-05 do *gate* 6 sem ninguem a declarar. Nao entra
#: em `ci/rls_exceptions.yaml`, que tem **uma** excepcao (a `audit_heads`, pelo
#: ADR-015) e deve continuar a ter so essa.
TABELAS_0034 = ("provisioning_step",)

#: O que a revisao 0036 (KAM-069) acrescenta: os destinos de transferencia.
#:
#: **Uma tabela, a `platform.tenant_destinations`**, e a vista
#: `v_transfer_audit` entra no `VISTAS` e nao aqui — o `pg_tables` nao lista
#: vistas.
#:
#: **Tem `tenant_id` ANULAVEL**, e e a primeira tabela deste repositorio com
#: `tenant_id` anulavel a entrar no X-05 — o nulo e o destino global de
#: infra-estrutura (criterio 1 do KAM-069). Leva RLS `FORCE` e **duas**
#: politicas permissivas: a `tenant_iso` do `db/rls.py`, intacta, e a
#: `destinos_globais`, `FOR SELECT`, que acrescenta as linhas globais sem tocar
#: na primeira. Nao entra em `ci/rls_exceptions.yaml`, que continua com **uma**
#: excepcao (a `audit_heads`, pelo ADR-015).
TABELAS_0036 = ("tenant_destinations",)

#: O que a revisao 0038 (KAM-070) acrescenta: os direitos do titular.
#:
#: **Duas tabelas**, e sao a primeira vez que uma revisao deste repositorio
#: acrescenta duas de uma vez ao topo da cadeia. As duas tem `tenant_id NOT
#: NULL`, pelo que **nenhuma** entra no `ANULAVEIS` do `test_catalogo.py` — ao
#: contrario da `tenant_destinations` ao lado — e as duas levam RLS `FORCE` com
#: a `tenant_iso` do `db/rls.py` e **nada mais**: uma politica permissiva so se
#: acrescenta quando ha linhas que nao sao de tenant nenhum, e um pedido do
#: titular e sempre de um tenant.
#:
#: A `erasure_ledger` e **append-only por privilegio** e nao por *trigger*:
#: nenhum papel leva `UPDATE` nem `DELETE`, o que a poe no grupo da
#: `tool_audit` e **fora** do grupo da `tool_idempotency` — e por isso nao tem
#: receita de `DELETE` nas sementes do X-05.
TABELAS_0038 = ("dsar_requests", "erasure_ledger")

#: O que a revisao 0040 (KAM-090) acrescenta: o aceite contratual versionado.
#:
#: **Duas tabelas, e so uma tem `tenant_id`.** A `contract_document` e texto de
#: plataforma — uma versao de ToS, DPA, aviso de privacidade ou lista de
#: subprocessadores — e nao tem tenant, como a `consent_texts` da `0015`: fica
#: fora do X-05 e do `ci/rls_exceptions.yaml`. A `contract_acceptance` tem
#: `tenant_id NOT NULL` **sem FK** (pre-alocado no registo, como o
#: `provisioning_step` da `0034`) e leva RLS `FORCE` com a `tenant_iso` e mais
#: nada.
#:
#: As duas sao **append-only por privilegio**: ninguem tem `UPDATE` nem
#: `DELETE`. A `contract_document` tem, alem disso, um *trigger* que recusa o
#: `UPDATE` ao dono — a imutabilidade do texto publicado e criterio do bloco.
TABELAS_0040 = ("contract_acceptance", "contract_document")

TABELAS = tuple(
    sorted(
        TABELAS_0001 + TABELAS_0003 + TABELAS_0004 + TABELAS_0005
        + TABELAS_0006 + TABELAS_0007 + TABELAS_0008 + TABELAS_0009
        + TABELAS_0010 + TABELAS_0011 + TABELAS_0012 + TABELAS_0013
        + TABELAS_0014 + TABELAS_0015 + TABELAS_0017 + TABELAS_0018
        + TABELAS_0019 + TABELAS_0021 + TABELAS_0022 + TABELAS_0024
        + TABELAS_0027 + TABELAS_0028 + TABELAS_0029 + TABELAS_0030
        + TABELAS_0032 + TABELAS_0033 + TABELAS_0034 + TABELAS_0036
        + TABELAS_0038 + TABELAS_0040
    )
)

#: O que existe em `platform` quando a base esta na revisao `0039`.
#:
#: O `downgrade` da `0040` leva a base para aqui. **Deriva do `TABELAS`**, e e
#: a unica da cadeia que o faz, porque e o topo dela: quem acrescentar uma
#: revisao a seguir poe a sua aqui e faz **esta** derivar da dela. **E descreve
#: tambem a `0038`**: a `0039` (KAM-060) cria uma funcao e um indice, e nenhuma
#: tabela.
TABELAS_ATE_0039 = tuple(sorted(set(TABELAS) - set(TABELAS_0040)))

#: O que existe em `platform` quando a base esta na revisao `0037`.
#:
#: O `downgrade` da `0038` leva a base para aqui. Deriva do `TABELAS_ATE_0039`
#: desde o KAM-090, que pos a sua revisao no topo — a nota do
#: `TABELAS_ATE_0032` explica por extenso o que custa esquecer-se disso.
#:
#: **E descreve tambem o que existe na `0036`**, pela mesma razao que o
#: `TABELAS_ATE_0035` descreve a `0034`: a `0037` (KAM-051) **nao cria tabela
#: nenhuma** — cria a vista `v_oferta_viva`, e o `pg_tables` nao lista vistas.
#: Medido no diff do PR #159 antes de se escrever esta linha, e nao assumido.
TABELAS_ATE_0037 = tuple(sorted(set(TABELAS_ATE_0039) - set(TABELAS_0038)))

#: O que existe em `platform` quando a base esta na revisao `0035`.
#:
#: O `downgrade` da `0036` leva a base para aqui. A `0035` (KAM-055) nao
#: cria tabela nenhuma — so FK —, pelo que esta lista descreve tambem o que
#: existe na `0034`.
TABELAS_ATE_0035 = tuple(sorted(set(TABELAS_ATE_0037) - set(TABELAS_0036)))

#: O que existe em `platform` quando a base esta na revisao `0033`.
#:
#: O `downgrade` da `0034` leva a base para aqui.
#:
#: **Deriva do `TABELAS_ATE_0035` e nao do `TABELAS`**, e e a setima vez que
#: esta nota se escreve: derivar do `TABELAS` deixava a tabela da revisao mais
#: nova dentro de uma lista que descreve uma base **anterior** a ela, e o
#: sintoma aparecia na suite de outro ticket.
TABELAS_ATE_0033 = tuple(sorted(set(TABELAS_ATE_0035) - set(TABELAS_0034)))

#: O que existe em `platform` quando a base esta na revisao `0032`.
#:
#: O `downgrade` da `0033` leva a base para aqui.
#:
#: **Deriva do `TABELAS_ATE_0033` e nao do `TABELAS`**, e com o KAM-069 passou a
#: derivar: esta tupla e a `ATE_0031` eram **as duas unicas** que derivavam de
#: `TABELAS` e subtraiam a mao cada revisao do topo, e a nota que aqui estava
#: avisava que «uma tabela nova no topo da cadeia entra nelas sozinha e avermelha
#: os ensaios de `downgrade` de **outras** revisoes — o sintoma aparece a
#: revisoes de distancia da causa».
#:
#: **O aviso estava escrito e falhou-se mesmo assim**, e isso mediu-se: a
#: `0036` entrou e o *gate* 8 deu **17** vermelhos, todos em ensaios de
#: `downgrade` das revisoes `0009` a `0019` — nenhum nesta linha nem na tabela
#: nova. Ler o aviso nao bastou; o que basta e nao haver excepcao para ler.
#:
#: Agora encadeia como as outras treze, e a propriedade e a mesma por
#: construcao: `ATE_0033` ja subtraiu tudo o que esta acima da `0033`, pelo que
#: aqui so falta a `0033`. Quem acrescentar uma tabela mexe **uma** linha — o
#: `TABELAS_ATE_<anterior>` da sua revisao — e mais nada.
TABELAS_ATE_0032 = tuple(sorted(set(TABELAS_ATE_0033) - set(TABELAS_0033)))

#: O que existe em `platform` quando a base esta na revisao `0031`.
#:
#: A `0031` (KAM-176) alarga um *trigger* e nao cria tabela, pelo que o conjunto
#: na `0031` e o da `0030`. O `downgrade` da `0032` leva a base para aqui.
#:
#: **Deriva do `TABELAS_ATE_0032`** pela razao que a nota dele escreve: era a
#: segunda e ultima que derivava de `TABELAS`, e deixou de o fazer com o KAM-069.
TABELAS_ATE_0031 = tuple(sorted(set(TABELAS_ATE_0032) - set(TABELAS_0032)))

#: O que existe em `platform` quando a base esta na revisao `0029`.
#:
#: Pela mesma razao das outras: o `downgrade` da `0030` leva a base para aqui, e
#: o teste do ciclo compara o conjunto com esta tupla.
#:
#: **Deriva do `TABELAS_ATE_0031` e nao do `TABELAS`**, e e a sexta vez que esta
#: nota se escreve: derivar do conjunto inteiro punha as **quatro** tabelas da
#: `0032` em todas as tuplas de revisoes anteriores, e os ensaios de
#: `downgrade` de outros modulos ficavam vermelhos a espera delas na revisao a
#: que descem.
TABELAS_ATE_0029 = tuple(sorted(set(TABELAS_ATE_0031) - set(TABELAS_0030)))

#: O que existe em `platform` quando a base esta na revisao `0028`.
#:
#: Pela mesma razao das outras: o `downgrade` da `0029` leva a base para aqui, e
#: o teste do ciclo compara o conjunto com esta tupla.
#: **Deriva do `TABELAS_ATE_0029` e nao do `TABELAS`**, e e a quinta vez que
#: esta nota se escreve: derivar do conjunto inteiro punha as **cinco** tabelas
#: da `0030` em todas as tuplas de revisoes anteriores, e os ensaios de
#: `downgrade` de outros modulos ficavam vermelhos a espera delas na revisao a
#: que descem. Mediu-se: trinta e um ensaios do *gate* 8 a falhar de uma vez.
TABELAS_ATE_0028 = tuple(sorted(set(TABELAS_ATE_0029) - set(TABELAS_0029)))

#: O que existe em `platform` quando a base esta na revisao `0027`.
#:
#: Pela mesma razao das outras: o `downgrade` da `0028` leva a base para aqui, e
#: o teste do ciclo compara o conjunto com esta tupla.
#:
#: **Deriva do `TABELAS_ATE_0028` e nao do `TABELAS`**, pela razao que a nota do
#: `TABELAS_ATE_0023` escreve e que a `0029` voltou a pagar o aviso: derivar do
#: conjunto inteiro punha as **quatro** tabelas da `0029` em todas as tuplas de
#: revisoes anteriores, e os ensaios de `downgrade` de outros modulos ficavam
#: vermelhos a espera delas na revisao a que descem. E a quarta vez que esta
#: armadilha morde — a `0027` custou quinze ensaios e a `0028` tres.
TABELAS_ATE_0027 = tuple(sorted(set(TABELAS_ATE_0028) - set(TABELAS_0028)))

#: O que existe em `platform` quando a base esta na revisao `0026`.
#:
#: Pela mesma razao das outras: o `downgrade` da `0027` leva a base para
#: aqui, e o teste do ciclo compara o conjunto com esta tupla. A `0025`
#: (KAM-047) cria o esquema `servicos` e a `0026` (KAM-035) alarga um
#: `CHECK`; nenhuma das duas cria tabela no `platform`, pelo que o conjunto
#: do `platform` na `0026` e o da `0024`.
#:
#: **Deriva do `TABELAS_ATE_0027` e nao do `TABELAS`**, pela razao que a nota do
#: `TABELAS_ATE_0023` ja escreve e que este ticket voltou a medir: derivar do
#: conjunto inteiro punha as duas tabelas da `0028` nas tuplas de todas as
#: revisoes anteriores, e **tres** ensaios de `downgrade` de outros modulos
#: ficaram vermelhos a espera delas na revisao a que desciam. E a terceira vez
#: que esta armadilha morde — a `0027` custou-lhe quinze ensaios.
TABELAS_ATE_0026 = tuple(sorted(set(TABELAS_ATE_0027) - set(TABELAS_0027)))

#: O que existe em `platform` quando a base esta na revisao `0023`.
#:
#: A `0023` (KAM-030) cria o esquema `dat` e nao toca no `platform`, pelo que o
#: conjunto do `platform` na `0023` e o da `0022`.
#:
#: **Deriva do `TABELAS_ATE_0026` e nao do `TABELAS`**, e a diferenca nao e
#: estilo: derivar do conjunto inteiro punha toda a tabela de uma revisao
#: **posterior** nas tuplas de revisoes anteriores. Medido pelo *gate* 8 ao
#: acrescentar a `payment_accounts` (`0027`): **quinze** ensaios de
#: `downgrade` de outros modulos passaram a esperar, na `0018`, uma tabela
#: que so existe na `0027`. E a forma que o `TABELAS_ATE_0020` ja usava.
TABELAS_ATE_0023 = tuple(sorted(set(TABELAS_ATE_0026) - set(TABELAS_0024)))

#: O que existe em `platform` quando a base esta na revisao `0021`.
#:
#: Pela mesma razao das outras: o `downgrade` da `0022` leva a base para aqui, e
#: o teste do ciclo compara o conjunto com esta tupla.
TABELAS_ATE_0021 = tuple(
    sorted(set(TABELAS_ATE_0026) - set(TABELAS_0022) - set(TABELAS_0024))
)

#: O que existe em `platform` quando a base esta na revisao `0020`.
#:
#: Pela mesma razao das outras: o `downgrade` da `0021` leva a base para aqui, e
#: o teste do ciclo compara o conjunto com esta tupla. **A `0020` e do KAM-026 e
#: nao cria tabela no `platform`** — cria o esquema `lg` e as duas de
#: `TABELAS_LG` —, pelo que o conjunto do `platform` na `0020` e o da `0019`.
TABELAS_ATE_0020 = tuple(sorted(set(TABELAS_ATE_0021) - set(TABELAS_0021)))

#: O que existe em `platform` quando a base esta na revisao `0018`.
#:
#: Pela mesma razao das outras: o `downgrade` da `0019` leva a base para aqui, e
#: o teste do ciclo compara o conjunto com esta tupla.
TABELAS_ATE_0018 = tuple(sorted(set(TABELAS_ATE_0020) - set(TABELAS_0019)))

#: O que existe em `platform` quando a base esta na revisao `0017`.
#:
#: Pela mesma razao das outras: o `downgrade` da `0018` leva a base para aqui, e
#: o teste do ciclo compara o conjunto com esta tupla.
TABELAS_ATE_0017 = tuple(sorted(set(TABELAS_ATE_0018) - set(TABELAS_0018)))

#: O que existe em `platform` quando a base esta na revisao `0016`.
#:
#: Pela mesma razao das outras: o `downgrade` da `0017` leva a base para aqui, e
#: o teste do ciclo compara o conjunto com esta tupla. **A `0016` e do KAM-018 e
#: nao cria tabela nenhuma** — sao dois `GRANT UPDATE` por coluna —, pelo que o
#: conjunto de tabelas da `0016` e o da `0015`.
TABELAS_ATE_0016 = tuple(sorted(set(TABELAS_ATE_0017) - set(TABELAS_0017)))

#: O que existe em `platform` quando a base esta na revisao `0014`.
#:
#: Pela mesma razao das outras: o `downgrade` da `0015` leva a base para aqui, e
#: o teste do ciclo compara o conjunto com esta tupla.
TABELAS_ATE_0014 = tuple(sorted(set(TABELAS_ATE_0016) - set(TABELAS_0015)))

#: O que existe em `platform` quando a base esta na revisao `0013`.
#:
#: Pela mesma razao das outras: o `downgrade` da `0014` leva a base para aqui, e
#: o teste do ciclo compara o conjunto com esta tupla.
TABELAS_ATE_0013 = tuple(sorted(set(TABELAS_ATE_0014) - set(TABELAS_0014)))

#: O que existe em `platform` quando a base esta na revisao `0011`.
#:
#: Pela mesma razao das outras: o `downgrade` da `0012` pode recusar (ha
#: objectos de midia e nao ha copia), e nesse caso a base fica aqui.
TABELAS_ATE_0011 = tuple(sorted(set(TABELAS_ATE_0013) - set(TABELAS_0012)))

#: O que existe em `platform` quando a base esta na revisao `0010`.
#:
#: Pela mesma razao das outras: o `downgrade` da `0011` pode recusar (ha
#: passagens ou contas de atendimento e nao ha copia), e nesse caso a base fica
#: aqui. **Desde a `0012`, chegar aqui passa primeiro pela `0012`**, que desce e
#: **compromete** antes de a `0011` levantar — uma transaccao por revisao.
TABELAS_ATE_0010 = tuple(sorted(set(TABELAS_ATE_0011) - set(TABELAS_0011)))

#: O que existe em `platform` quando a base esta na revisao `0009`.
#:
#: Pela mesma razao das outras: o `downgrade` da `0010` pode recusar (ha envios
#: ou templates e nao ha copia), e nesse caso a base fica aqui. **Desde a
#: `0011`, chegar aqui passa primeiro pela `0011`**, que desce e **compromete**
#: antes de a `0010` levantar — uma transaccao por revisao.
TABELAS_ATE_0009 = tuple(sorted(set(TABELAS_ATE_0010) - set(TABELAS_0010)))

#: O que existe em `platform` quando a base esta na revisao `0008`.
#:
#: Pela mesma razao do `TABELAS_ATE_0003` e do `TABELAS_ATE_0004`: o
#: `downgrade` da `0009` pode recusar (ha conversas e nao ha copia), e nesse
#: caso a base fica aqui.
TABELAS_ATE_0008 = tuple(sorted(set(TABELAS_ATE_0009) - set(TABELAS_0009)))

#: O que existe em `platform` quando a base esta na revisao `0004`.
#:
#: Pela mesma razao do `TABELAS_ATE_0003`, uma revisao a frente: um
#: `downgrade 0003` desce primeiro a 0004 (que confirma) e so depois tenta a
#: 0003. Se a 0003 recusar, a base fica em **0004** — e os testes que provam
#: essa recusa comparam com isto, nao com a cabeca.
TABELAS_ATE_0004 = tuple(sorted(TABELAS_0001 + TABELAS_0003 + TABELAS_0004))

#: O que existe em `platform` quando a base esta na revisao `0003`.
#:
#: Faz falta porque o Alembic corre **uma transaccao por revisao**
#: (`transaction_per_migration=True` em `migrations/env.py`): um `downgrade 0002`
#: a partir da cabeca desce a `0004` — que confirma — e so depois tenta a
#: `0003`. Se a `0003` recusar (tem linhas de identidade e nao ha copia), a base
#: fica em `0003`, nao em `head`. Os testes que provam essa recusa comparam com
#: esta lista, e nao com `TABELAS`.
TABELAS_ATE_0003 = tuple(sorted(TABELAS_0001 + TABELAS_0003))


def exigir_base_descartavel() -> None:
    base = os.environ.get("KAMBA_DB_NAME", "")
    # Igualdade e nao sufixo: com `endswith("_gate8")`, uma base chamada
    # `producao_gate8` passava o trinco.
    if base != BASE_DESCARTAVEL:
        raise unittest.SkipTest(
            f"KAMBA_DB_NAME={base!r} nao e {BASE_DESCARTAVEL!r}. Os testes do "
            "gate 8 apagam o schema `platform` e so correm contra a base "
            "descartavel que `python db/gate_bd.py` cria."
        )


def alembic_cli(*argumentos: str) -> subprocess.CompletedProcess:
    """Corre o Alembic pela linha de comandos, como o criterio de aceitacao diz.

    Um processo novo por chamada. E o que `test_migracao.TestCiclo` usa para o
    ciclo `upgrade -> downgrade -> upgrade` do criterio 1 do KAM-003; o resto
    da suite usa `alembic`, que faz o mesmo sem pagar o arranque do processo.
    """
    return subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "migrations/alembic.ini", *argumentos],
        cwd=DB,
        capture_output=True,
        text=True,
    )


def alembic(*argumentos: str) -> subprocess.CompletedProcess:
    """Corre o Alembic **neste processo**, pela entrada da linha de comandos.

    `CommandLine` e a classe que o executavel `alembic` usa: o mesmo analisador
    de argumentos, a mesma leitura do `alembic.ini`, o mesmo `env.py`, as mesmas
    revisoes. O que nao se paga e o arranque de um interpretador e a importacao
    do SQLAlchemy em cada chamada — medido em Windows, oito a nove segundos por
    chamada, numa suite que faz dezenas. Devolve o mesmo que `alembic_cli`:
    codigo de saida, saida e erros, com o *traceback* de uma revisao que falhe
    nos erros. `TestCiclo` confere que os dois dizem o mesmo.

    A `Config` constroi-se aqui, e nao por `CommandLine.main`, so para lhe dar
    onde escrever: a omissao do seu `stdout` e o `sys.stdout` do momento em que
    o modulo foi importado, que um `redirect_stdout` ja nao apanha.
    """
    import contextlib
    import io
    import traceback

    from alembic.config import CommandLine, Config

    saida, erros = io.StringIO(), io.StringIO()
    codigo = 0
    comando = ["-c", "migrations/alembic.ini", *argumentos]
    with (
        contextlib.chdir(DB),
        contextlib.redirect_stdout(saida),
        contextlib.redirect_stderr(erros),
    ):
        try:
            linha = CommandLine(prog="alembic")
            opcoes = linha.parser.parse_args(comando)
            linha.run_cmd(
                Config(file_="migrations/alembic.ini", stdout=saida, cmd_opts=opcoes),
                opcoes,
            )
        except SystemExit as saiu:
            codigo = saiu.code if isinstance(saiu.code, int) else int(saiu.code is not None)
        except Exception:  # noqa: BLE001 — uma revisao que falha e um resultado, nao um erro do teste
            traceback.print_exc(file=erros)
            codigo = 1
    return subprocess.CompletedProcess(comando, codigo, saida.getvalue(), erros.getvalue())


def _exigir_sucesso(resultado: subprocess.CompletedProcess, argumentos: tuple) -> None:
    if resultado.returncode != 0:
        raise AssertionError(
            f"alembic {' '.join(argumentos)} falhou ({resultado.returncode}):\n"
            f"{resultado.stdout}\n{resultado.stderr}"
        )


def alembic_ok(*argumentos: str) -> None:
    _exigir_sucesso(alembic(*argumentos), argumentos)


def alembic_cli_ok(*argumentos: str) -> None:
    _exigir_sucesso(alembic_cli(*argumentos), argumentos)


def sqlstate(excepcao: BaseException) -> str:
    """O SQLSTATE de um erro do pg8000 (campo `C` da mensagem do servidor)."""
    for argumento in excepcao.args:
        if isinstance(argumento, dict) and "C" in argumento:
            return str(argumento["C"])
    return ""


#: SQLSTATE por nome, para os testes dizerem o que esperam e nao um numero.
VIOLACAO_DE_CHECK = "23514"
VIOLACAO_DE_UNICIDADE = "23505"
VIOLACAO_DE_FK = "23503"
VIOLACAO_DE_NOT_NULL = "23502"
PRIVILEGIO_INSUFICIENTE = "42501"


def revisao_de_cabeca() -> str:
    """A revisao mais alta de `migrations/versions/` (os ficheiros sao `NNNN_*.py`)."""
    return max(
        ficheiro.name[:4]
        for ficheiro in (DB / "migrations" / "versions").glob("[0-9][0-9][0-9][0-9]_*.py")
    )


def em_head() -> bool:
    """A base ja esta na revisao de cabeca? Sem lancar um processo do Alembic.

    Cada `alembic upgrade head` e um processo novo, e sao segundos — mesmo
    quando nao ha nada para fazer, que e o caso de quase todas as classes de
    teste. Pergunta-se a base em que revisao esta e so se chama o Alembic
    quando a resposta nao e a cabeca. Quem prova as migracoes em si
    (`test_migracao.TestCiclo`, `test_identidade_schema.TestDowngradeDa0003`)
    chama o Alembic sempre, e nao passa por aqui.
    """
    import pg8000.dbapi

    conexao = ligacao.ligar("admin")
    try:
        cursor = conexao.cursor()
        cursor.execute("SELECT version_num FROM public.alembic_version")
        return [tuple(linha) for linha in cursor.fetchall()] == [(revisao_de_cabeca(),)]
    except pg8000.dbapi.DatabaseError:
        return False  # a tabela de versao ainda nao existe: base por migrar
    finally:
        conexao.close()


class ComBase(unittest.TestCase):
    """Garante papeis criados e o schema em `head` antes de cada classe."""

    @classmethod
    def setUpClass(cls) -> None:
        exigir_base_descartavel()
        bootstrap.aplicar()
        if not em_head():
            alembic_ok("upgrade", "head")

    def setUp(self) -> None:
        self._conexoes = []

    def tearDown(self) -> None:
        for conexao in self._conexoes:
            try:
                conexao.rollback()
            finally:
                conexao.close()

    def ligar(self, identidade: str):
        """Ligacao que nunca faz `commit`: cada teste desfaz o que escreveu."""
        conexao = ligacao.ligar(identidade)
        self._conexoes.append(conexao)
        return conexao

    def consultar(self, sql: str, parametros: tuple = (), identidade: str = "admin"):
        cursor = self.ligar(identidade).cursor()
        cursor.execute(sql, parametros)
        # O pg8000 devolve listas; normaliza-se para tuplos, que se comparam
        # e entram em conjuntos.
        return [tuple(linha) for linha in cursor.fetchall()]

    def assertErroSql(self, esperado: str, cursor, sql: str, parametros: tuple = ()):
        """A instrucao tem de falhar, e com o SQLSTATE esperado.

        Corre dentro de um `SAVEPOINT`: um erro aborta a transaccao inteira no
        PostgreSQL, e sem ele o teste perdia o que ja tinha inserido (o tenant
        de que o caso negativo precisa) e nao podia continuar na mesma ligacao.
        """
        import pg8000.dbapi

        cursor.execute("SAVEPOINT caso_negativo")
        try:
            with self.assertRaises(pg8000.dbapi.DatabaseError) as capturado:
                cursor.execute(sql, parametros)
        finally:
            cursor.execute("ROLLBACK TO SAVEPOINT caso_negativo")
        self.assertEqual(
            sqlstate(capturado.exception),
            esperado,
            f"falhou, mas nao pela razao esperada: {capturado.exception}",
        )


#: Onde vivem as constantes de SQL do consumidor (KAM-006).
CONSULTAS_DO_CONSUMIDOR = (
    Path(__file__).resolve().parents[2]
    / "packages" / "core-ts" / "src" / "eventos" / "consultas_consumo.ts"
)


class ConsultaDoTypeScript:
    """Uma constante de SQL do TypeScript, pronta para o `pg8000`.

    Existe para que uma suite de base de dados exercite **o SQL do modulo** e
    nao uma copia dele: uma copia prova que a copia funciona.

    **O `pg8000` nao tem `$n`: tem `%s`, e liga-os pela ordem em que aparecem
    no texto.** O `SQL_FECHAR_ACCAO` escreve `SET estado = $2, resultado = $3
    ... WHERE idempotency_key = $1`, pelo que a troca ingenua de `$n` por `%s`
    muda o significado dos argumentos — e o PostgreSQL recusou, a primeira
    execucao desta classe, um `'feita'` onde esperava `jsonb`. Por isso guarda
    a **ordem** dos marcadores e reordena o que se lhe passa: quem chama
    escreve os argumentos pela numeracao do documento.
    """

    def __init__(self, nome: str, ficheiro: Path | None = None) -> None:
        caminho = CONSULTAS_DO_CONSUMIDOR if ficheiro is None else ficheiro
        texto = caminho.read_text(encoding="utf-8")
        achado = re.search(rf"export const {nome} = `(.*?)`;", texto, re.S)
        if achado is None:
            raise AssertionError(f"nao se encontrou {nome} em {caminho.name}")
        self.nome = nome
        self.fonte = achado.group(1)
        self.ordem = [int(n) for n in re.findall(r"\$(\d+)", self.fonte)]
        # **O `%` literal duplica-se, e isto nao e cosmetica.** O `paramstyle`
        # do pg8000 e `format`: um `%` que nao seja `%s` ou `%%` levanta
        # `InterfaceError: Only %s and %% are supported in the query`. O
        # `SQL_PESQUISAR` do KAM-043 e o primeiro a trazer um — `nome % $2`, o
        # operador de semelhanca de trigramas do `pg_trgm`, que e o unico que
        # usa o indice GIN (o `similarity()` na clausula nao o usa). O SQL do
        # modulo esta correcto; o que precisa de escape e o driver desta suite,
        # e o escape e aqui para que o modulo nao tenha de saber que ela existe.
        #
        # **Antes** do `$n -> %s`, senao duplicava os `%s` que acabou de criar.
        self.sql = re.sub(r"\$\d+", "%s", self.fonte.replace("%", "%%"))

    def args(self, *valores: object) -> tuple[object, ...]:
        """Os `valores` — na numeracao do documento — pela ordem do texto.

        **Um marcador pode repetir-se, e desde o KAM-045 repete-se.** A
        comparacao e sobre o conjunto dos marcadores e nao sobre a lista: o
        `SQL_RESERVAR` das reservas de stock escreve o `$3` duas vezes — uma no
        `SET stock_reservada = stock_reservada + $3` e outra no predicado
        `stock_quantidade - stock_reservada >= $3` —, e as duas tem de ser o
        mesmo numero, senao a reserva promete uma quantidade e verifica outra.

        O `return` desta funcao **ja** tratava o caso: mapeia por posicao, pelo
        que um marcador repetido recebe o mesmo valor nas duas posicoes. Era so
        a asercao que o proibia, e proibia SQL legitimo — passar a quantidade
        como `$3` e `$4` para satisfazer o verificador era criar dois parametros
        que tem de ser iguais, que e a forma de os deixar divergir.

        O que a asercao continua a garantir e o que importa: os marcadores sao
        **exactamente** `$1` a `$n`, sem buracos e sem numeros a mais.
        """
        if sorted(set(self.ordem)) != list(range(1, len(valores) + 1)):
            raise AssertionError(
                f"{self.nome} tem os marcadores {self.ordem} e deram-se "
                f"{len(valores)} argumentos"
            )
        return tuple(valores[n - 1] for n in self.ordem)
