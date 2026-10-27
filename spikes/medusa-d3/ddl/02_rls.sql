-- Spike KAM-041 — RLS `FORCE` sobre as tabelas do ficheiro 01, para medir
-- ISO-39..42 («sessao SQL com `app.tenant_id` de A: SELECT/UPDATE/DELETE em
-- linhas de B; sessao sem `app.tenant_id`» -> 0 linhas, falha fechada).
--
-- A politica e a de `db/rls.py`, que e o unico sitio do repositorio onde ela se
-- escreve, e o nome e o **canonico**: `tenant_iso`. O `docs/tecnica/03` §5.5
-- chama-lhe `tenant_isolamento`; a divergencia esta registada no dicionario
-- §3.2 (emenda 1.5) e resolve-se a favor de `tenant_iso`. Este ficheiro repete
-- o SQL em vez de importar `db/rls.py` porque `rls.py` emite por `op.execute`
-- do Alembic, e estas tabelas nao sao uma revisao (ver o cabecalho do 01).
--
-- `FORCE` e o que faz a prova valer: sem ele o dono das tabelas
-- (`kamba_migrator`) ve tudo, e o teste passava por nao ter barreira nenhuma.

ALTER TABLE platform.orders_mirror ENABLE ROW LEVEL SECURITY;
ALTER TABLE platform.orders_mirror FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_iso ON platform.orders_mirror
  USING      (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
  WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

ALTER TABLE platform.order_intents ENABLE ROW LEVEL SECURITY;
ALTER TABLE platform.order_intents FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_iso ON platform.order_intents
  USING      (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
  WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

ALTER TABLE platform.order_state_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE platform.order_state_log FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_iso ON platform.order_state_log
  USING      (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
  WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

ALTER TABLE platform.stock_reservations ENABLE ROW LEVEL SECURITY;
ALTER TABLE platform.stock_reservations FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_iso ON platform.stock_reservations
  USING      (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
  WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

ALTER TABLE platform.offer_terms ENABLE ROW LEVEL SECURITY;
ALTER TABLE platform.offer_terms FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_iso ON platform.offer_terms
  USING      (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
  WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

ALTER TABLE platform.order_reconciliation_issues ENABLE ROW LEVEL SECURITY;
ALTER TABLE platform.order_reconciliation_issues FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_iso ON platform.order_reconciliation_issues
  USING      (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
  WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

ALTER TABLE platform.events_outbox ENABLE ROW LEVEL SECURITY;
ALTER TABLE platform.events_outbox FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_iso ON platform.events_outbox
  USING      (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
  WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

ALTER TABLE platform.spike_stock_levels ENABLE ROW LEVEL SECURITY;
ALTER TABLE platform.spike_stock_levels FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_iso ON platform.spike_stock_levels
  USING      (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
  WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

-- `order_state_graph` nao tem `tenant_id`: e a tabela de transicoes permitidas,
-- igual para todos os tenants. Sem RLS, e de leitura para a aplicacao.

-- `kamba_batch` (BYPASSRLS, auditado) e quem semeia e quem corre os *jobs*
-- nomeados: o varredor de expiracao do §6.5 e a reconciliacao do §10.3 leem
-- todos os tenants por desenho, e e por isso que a RLS nao lhes serve de
-- barreira — o que os limita e o papel ser nomeado e auditado.
GRANT SELECT, INSERT, UPDATE, DELETE ON
  platform.orders_mirror, platform.order_intents, platform.stock_reservations,
  platform.offer_terms, platform.order_reconciliation_issues,
  platform.spike_stock_levels, platform.order_state_log, platform.events_outbox,
  platform.order_state_graph
  TO kamba_batch;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA platform TO kamba_batch;

GRANT USAGE ON SCHEMA platform TO kamba_app;
GRANT SELECT, INSERT, UPDATE ON
  platform.orders_mirror, platform.order_intents, platform.stock_reservations,
  platform.offer_terms, platform.order_reconciliation_issues,
  platform.spike_stock_levels
  TO kamba_app;
-- `order_state_log` e `events_outbox` sao append-only (§5.6): so INSERT e
-- SELECT, nunca UPDATE nem DELETE.
GRANT SELECT, INSERT ON platform.order_state_log, platform.events_outbox TO kamba_app;
GRANT SELECT ON platform.order_state_graph TO kamba_app;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA platform TO kamba_app;
