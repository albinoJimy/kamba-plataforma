-- Spike KAM-041 — `evt_emitir`, e porque e que ela existe aqui.
--
-- A primeira execucao do spike escreveu no `events_outbox` com um `INSERT`
-- directo, e o ISO-46 apanhou o resultado: passou um evento cujo **envelope JSON
-- dizia o tenant B** enquanto a **coluna dizia o tenant A**. Nenhuma constraint
-- impede a incoerencia, porque nenhuma constraint pode: a coerencia entre uma
-- coluna e um campo dentro de um `jsonb` nao se declara, constroi-se.
--
-- E o desenho canonico ja a constroi. O `docs/tecnica/06` §6.1 nao da `INSERT`
-- no `events_outbox` a quem emite: da uma funcao, `evt_emitir`, que **recebe o
-- payload e monta o envelope**. Quem emite nao tem por onde dizer um tenant no
-- envelope, porque nao escreve o envelope.
--
-- Este ficheiro poe essa funcao no spike e **retira** ao `kamba_app` o `INSERT`
-- directo que o `02_rls.sql` lhe tinha dado. O ISO-45 e o ISO-46 passam a medir
-- o desenho em vez de medirem o atalho do harness — que era o defeito real do
-- primeiro resultado, e nao um defeito do desenho.
--
-- Desvios declarados face ao §6.1, porque o spike nao os mede: sem
-- `evt_agregado_seq` (a sequencia por agregado vem de um `max()+1`), sem
-- `evt_subscricoes`, sem particionamento por hash do tenant, e sem o gatilho
-- anti-PII que recusa padroes de telefone. Quem escrever o EPIC-07 parte do
-- §6.1, nao daqui.

REVOKE INSERT ON platform.events_outbox FROM kamba_app;

CREATE FUNCTION platform.evt_emitir(
  p_tipo      text,
  p_versao    smallint,
  p_tenant    uuid,
  p_agg_tipo  text,
  p_agg_id    text,
  p_payload   jsonb,
  p_trace     text DEFAULT NULL
) RETURNS uuid
LANGUAGE plpgsql
-- `SECURITY DEFINER`: o `kamba_app` ja nao tem `INSERT` na tabela, e e isso
-- que faz o envelope ser incontornavel. A funcao corre como dona (o
-- `kamba_migrator`), que **tambem** esta sob a politica por causa do `FORCE` —
-- logo a RLS continua a decidir, e um `p_tenant` que nao seja o do contexto e
-- recusado pelo `WITH CHECK`. E o que o ISO-45 mede.
SECURITY DEFINER
SET search_path = platform, pg_catalog
AS $$
DECLARE
  v_id       uuid := gen_random_uuid();
  v_seq      bigint;
  v_envelope jsonb;
BEGIN
  SELECT coalesce(max(agregado_seq), 0) + 1 INTO v_seq
    FROM platform.events_outbox
   WHERE agregado_tipo = p_agg_tipo AND agregado_id = p_agg_id;

  -- O envelope e **construido aqui**. O chamador da o payload e o tenant; o
  -- `tenant_id` do envelope e o mesmo valor que vai para a coluna, por
  -- construcao, e nao por confianca.
  v_envelope := jsonb_build_object(
    'id',         v_id::text,
    'tipo',       p_tipo,
    'versao',     p_versao,
    'tenant_id',  p_tenant::text,
    'trace_id',   p_trace,
    'ocorrido_em', to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"'),
    'payload',    p_payload
  );

  INSERT INTO platform.events_outbox
    (event_id, tipo, versao, tenant_id, agregado_tipo, agregado_id,
     agregado_seq, particao, envelope)
  VALUES
    (v_id, p_tipo, p_versao, p_tenant, p_agg_tipo, p_agg_id,
     v_seq, (hashtextextended(p_tenant::text || p_agg_id, 0) & 15)::smallint,
     v_envelope);

  RETURN v_id;
END;
$$;

REVOKE ALL ON FUNCTION platform.evt_emitir(
  text, smallint, uuid, text, text, jsonb, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION platform.evt_emitir(
  text, smallint, uuid, text, text, jsonb, text) TO kamba_app;
