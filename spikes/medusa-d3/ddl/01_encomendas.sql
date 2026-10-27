-- Spike KAM-041 — tabelas do ciclo de vida da encomenda, para medir AC-4, AC-5,
-- AC-6 e ISO-39..42.
--
-- ISTO NAO E UMA MIGRACAO. As tabelas canonicas de `platform` que o ciclo de
-- vida da encomenda precisa (`orders_mirror`, `order_intents`,
-- `order_state_log`, `stock_reservations`, `offer_terms`, `events_outbox`)
-- **ainda nao existem** em `db/migrations/versions/` — a revisao mais recente
-- e a 0003 (identidade de contacto), e as tabelas de encomenda sao do KAM-044
-- e do KAM-045. O spike precisa delas para medir, e so para medir: este
-- ficheiro cria-as na base descartavel do harness, por cima das revisoes
-- 0001-0003 que o Alembic aplica.
--
-- O DDL segue `docs/tecnica/03_Core_Comercio_Medusa.md` §5.4 (encomendas,
-- intencoes, reservas, ofertas), §5.5 (RLS, no ficheiro 02) e
-- `docs/tecnica/06_Dados_Eventos_Analytics.md` §6.1 (`events_outbox`).
-- Onde se desvia, a linha diz porque. Quem escrever o KAM-044 e o KAM-045
-- parte do §5.4 e nao daqui: isto e o instrumento de medicao, nao o desenho.

-- `contacts` vem da revisao 0003. `tenants` vem da 0001, e ja traz
-- `medusa_sales_channel_id` e `medusa_merchant_id` — as duas colunas de que a
-- opcao B depende.

CREATE TABLE platform.orders_mirror (
  id                     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id              uuid NOT NULL REFERENCES platform.tenants(id),
  -- **Chave estrangeira composta, e nao `REFERENCES platform.contacts(contact_id)`.**
  --
  -- O §5.4 do `docs/tecnica/03` escreve a FK pela coluna so:
  --     contact_id uuid NOT NULL REFERENCES platform.contacts(contact_id)
  -- e o ISO-58 deste spike apanhou o que isso permite. Medido a 2026-10-27:
  -- com `ctx` do tenant A e o `contact_id` de B, o `create_order` **passou** e
  -- criou uma encomenda de A a apontar para um contacto de B. Nem a FK nem a
  -- RLS o impedem: a FK e satisfeita pela chave primaria de `contacts`, que nao
  -- inclui o tenant, e a RLS olha para o `tenant_id` **da linha** da encomenda,
  -- que e o do contexto e esta correcto.
  --
  -- A revisao 0003 ja criou o unico que torna a forma composta possivel
  -- (`contacts_tenant_contact_uq UNIQUE (tenant_id, contact_id)`). E esta a
  -- forma que o spike mede, e o defeito do §5.4 esta registado no relatorio e
  -- tem ticket proprio: a correccao da tabela de producao e do KAM-044.
  contact_id             uuid NOT NULL,
  origem                 text NOT NULL DEFAULT 'pme'
                         CHECK (origem IN ('pme','plataforma')),
  numero_publico         text NOT NULL,
  intent_key             text NOT NULL,
  medusa_order_id        text,
  estado                 text NOT NULL DEFAULT 'criada'
                         CHECK (estado IN ('criada','aguarda_pagamento','pendente_confirmacao',
                                           'paga','em_entrega','entregue','expirada','cancelada',
                                           'reembolso_pendente')),
  confirmacao_dono       text NOT NULL DEFAULT 'nao_aplicavel'
                         CHECK (confirmacao_dono IN ('nao_aplicavel','pendente','confirmada',
                                                     'recusada','expirada')),
  total_minor            bigint NOT NULL CHECK (total_minor >= 0),
  currency               char(3) NOT NULL DEFAULT 'AOA',
  lines_snapshot         jsonb NOT NULL,
  entrega_modo           text NOT NULL DEFAULT 'levantamento'
                         CHECK (entrega_modo IN ('levantamento','entrega')),
  expira_at              timestamptz,
  paga_at                timestamptz,
  paga_via               text CHECK (paga_via IN ('provider_autenticado','manual_auditado','cod_manual')),
  excepcao               text CHECK (excepcao IN ('pagamento_tardio_sem_stock','pagamento_duplicado',
                                                  'valor_divergente')),
  entregue_at            timestamptz,
  entrega_confirmada_por text CHECK (entrega_confirmada_por IN ('cliente','dono','estafeta')),
  version                integer NOT NULL DEFAULT 1,
  criado_at              timestamptz NOT NULL DEFAULT now(),
  atualizado_at          timestamptz NOT NULL DEFAULT now(),
  deleted_at             timestamptz,
  UNIQUE (tenant_id, intent_key),
  UNIQUE (tenant_id, numero_publico),
  CONSTRAINT orders_mirror_contacto_do_mesmo_tenant_fk
    FOREIGN KEY (tenant_id, contact_id)
    REFERENCES platform.contacts (tenant_id, contact_id),
  -- O unico que torna possiveis as FK compostas das tabelas filhas
  -- (`order_intents`, `order_state_log`, `stock_reservations`,
  -- `order_reconciliation_issues`). `id` ja e chave primaria; isto acrescenta
  -- o par.
  CONSTRAINT orders_mirror_tenant_id_uq UNIQUE (tenant_id, id)
);

CREATE INDEX orders_mirror_estado_idx
  ON platform.orders_mirror (tenant_id, estado, criado_at DESC);
CREATE INDEX orders_mirror_expira_idx
  ON platform.orders_mirror (expira_at)
  WHERE estado IN ('aguarda_pagamento','pendente_confirmacao');

CREATE TABLE platform.order_intents (
  tenant_id  uuid NOT NULL REFERENCES platform.tenants(id),
  intent_key text NOT NULL,
  draft_hash bytea NOT NULL,
  estado     text NOT NULL DEFAULT 'em_curso'
             CHECK (estado IN ('em_curso','concluida','falhada')),
  order_id   uuid,
  criado_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, intent_key),
  CONSTRAINT order_intents_do_mesmo_tenant_fk
    FOREIGN KEY (tenant_id, order_id)
    REFERENCES platform.orders_mirror (tenant_id, id)
);

-- A FK e composta, como em todas as que ligam duas tabelas com `tenant_id`.
-- E a regra que o ISO-58 deste spike obrigou a escrever (ver a nota do
-- `orders_mirror.contact_id`), e aplica-se aqui tambem — nao se declara uma
-- regra e deixa-se o proprio instrumento a violar-la.
CREATE TABLE platform.order_state_log (
  id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  tenant_id  uuid NOT NULL,
  order_id   uuid NOT NULL,
  de         text NOT NULL,
  para       text NOT NULL,
  causa      text NOT NULL,
  evento_id  text,
  actor_kind text NOT NULL,
  actor_id   text,
  em         timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT order_state_log_do_mesmo_tenant_fk
    FOREIGN KEY (tenant_id, order_id)
    REFERENCES platform.orders_mirror (tenant_id, id)
);

CREATE TABLE platform.stock_reservations (
  id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id             uuid NOT NULL REFERENCES platform.tenants(id),
  order_id              uuid NOT NULL,
  line_no               smallint NOT NULL,
  sku                   text NOT NULL,
  qty                   integer NOT NULL CHECK (qty > 0),
  estado                text NOT NULL DEFAULT 'ativa'
                        CHECK (estado IN ('ativa','consumida','libertada','expirada')),
  expira_at            timestamptz NOT NULL,
  medusa_reservation_id text,
  criado_at             timestamptz NOT NULL DEFAULT now(),
  UNIQUE (order_id, line_no),
  CONSTRAINT stock_reservations_do_mesmo_tenant_fk
    FOREIGN KEY (tenant_id, order_id)
    REFERENCES platform.orders_mirror (tenant_id, id)
);

CREATE INDEX stock_reservations_expiry_idx
  ON platform.stock_reservations (expira_at) WHERE estado = 'ativa';

CREATE TABLE platform.offer_terms (
  tenant_id           uuid NOT NULL REFERENCES platform.tenants(id),
  sku                 text NOT NULL,
  medusa_variant_id   text,
  preco_tipo          text NOT NULL CHECK (preco_tipo IN ('fixo','a_partir_de','sob_consulta')),
  preco_minor         bigint CHECK (preco_minor >= 0),
  currency            char(3) NOT NULL DEFAULT 'AOA',
  preco_atualizado_at timestamptz,
  preco_valido_ate    timestamptz,
  stock_modo          text NOT NULL DEFAULT 'indicativo'
                      CHECK (stock_modo IN ('garantido','indicativo','confirmar_dono')),
  stock_verificado_at timestamptz,
  estado              text NOT NULL DEFAULT 'rascunho'
                      CHECK (estado IN ('rascunho','publicado','pausado','arquivado')),
  categoria_restrita  text,
  deleted_at          timestamptz,
  PRIMARY KEY (tenant_id, sku),
  CHECK ((preco_tipo = 'sob_consulta' AND preco_minor IS NULL)
      OR (preco_tipo <> 'sob_consulta' AND preco_minor IS NOT NULL))
);

-- §10.3: onde a reconciliacao registo <-> espelho grava as divergencias.
-- A metrica do AC-5 e «divergencias abertas > 5 min = 0», e le-se daqui.
CREATE TABLE platform.order_reconciliation_issues (
  id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  tenant_id     uuid NOT NULL REFERENCES platform.tenants(id),
  order_id      uuid,
  intent_key    text,
  tipo          text NOT NULL
                CHECK (tipo IN ('registo_sem_espelho','espelho_sem_registo','total_divergente',
                                'reserva_orfa','estado_divergente')),
  detectado_at  timestamptz NOT NULL DEFAULT now(),
  resolvido_at  timestamptz,
  CONSTRAINT order_reconciliation_do_mesmo_tenant_fk
    FOREIGN KEY (tenant_id, order_id)
    REFERENCES platform.orders_mirror (tenant_id, id)
);

-- `events_outbox` de `docs/tecnica/06` §6.1, reduzido ao que o spike mede:
-- ISO-43..46 (consumidor de A a ler o outbox; envelope com `tenant_id`
-- forjado) e AC-5 (o evento `order.created` escrito na mesma transaccao).
-- Desvio declarado: sem `evt_agregado_seq`, sem `evt_subscricoes`, sem a
-- funcao `evt_emitir` e sem o gatilho anti-PII — o spike nao mede o
-- publicador nem o roteamento por finalidade, que sao do EPIC-07.
CREATE TABLE platform.events_outbox (
  id                   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  event_id             uuid NOT NULL UNIQUE,
  tipo                 text NOT NULL,
  versao               smallint NOT NULL,
  tenant_id            uuid NOT NULL REFERENCES platform.tenants(id),
  agregado_tipo        text NOT NULL,
  agregado_id          text NOT NULL,
  agregado_seq         bigint NOT NULL,
  particao             smallint NOT NULL,
  envelope             jsonb NOT NULL,
  criado_at            timestamptz NOT NULL DEFAULT now(),
  publicado_at         timestamptz,
  tentativas           int NOT NULL DEFAULT 0,
  proxima_tentativa_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (agregado_tipo, agregado_id, agregado_seq)
);

CREATE INDEX events_outbox_pendentes
  ON platform.events_outbox (proxima_tentativa_at, id) WHERE publicado_at IS NULL;

-- Stock do spike. No desenho (§10.1) a autoridade do stock e o Registo: o
-- Medusa Inventory na opcao B, `commerce.stock_levels` na opcao C. Esta tabela
-- e o **comparador** do AC-3: a mesma prova de sobrevenda corre contra o
-- Medusa Inventory e contra um `UPDATE ... WHERE quantidade - reservada >= :q`
-- (§6.4), e o relatorio mostra os dois numeros. Sem o comparador, um zero no
-- Medusa nao se distingue de um zero por o teste nao ter concorrido.
CREATE TABLE platform.spike_stock_levels (
  tenant_id  uuid NOT NULL REFERENCES platform.tenants(id),
  sku        text NOT NULL,
  quantidade integer NOT NULL CHECK (quantidade >= 0),
  reservada  integer NOT NULL DEFAULT 0 CHECK (reservada >= 0),
  CHECK (reservada <= quantidade),
  PRIMARY KEY (tenant_id, sku)
);

-- §6.2: a tabela de transicoes e dados, validados por gatilho. O spike precisa
-- dela para o criterio de saida do epic «toda a transicao fora de
-- `order_state_graph` e rejeitada pelo gatilho» — que nao e um AC do KAM-041,
-- mas e o que torna `transition` mensuravel no ISO-04.
CREATE TABLE platform.order_state_graph (
  de   text NOT NULL,
  para text NOT NULL,
  PRIMARY KEY (de, para)
);
