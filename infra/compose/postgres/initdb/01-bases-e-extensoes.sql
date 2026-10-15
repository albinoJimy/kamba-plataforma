-- Bases e extensoes do ambiente de desenvolvimento (KAM-001).
--
-- `docs/tecnica/09` §3.1: bases separadas para plataforma, Medusa e Chatwoot. A
-- separacao e por base e nao por schema para que o Medusa e o Chatwoot — que
-- gerem as suas proprias migracoes — nao possam tocar no schema `platform`.
--
-- Este ficheiro cria **bases e extensoes vazias**, e mais nada. Tabelas,
-- `tenants`, `entitlements`, RLS e migracoes sao o KAM-003 e o KAM-004. Se
-- aparecer aqui um `CREATE TABLE`, o escopo escorregou.

\set ON_ERROR_STOP on

-- A base da plataforma e criada pelo `POSTGRES_DB` do entrypoint; faltam as outras.
CREATE DATABASE kamba_medusa;
CREATE DATABASE kamba_chatwoot;

-- pgvector 0.8.7 e pg_trgm na base da plataforma. O indice de pesquisa (KAM-035+)
-- vive aqui; o Medusa e o Chatwoot ficam sem vectores.
--
-- Nao se usa `\connect`: o entrypoint da imagem ja corre este ficheiro ligado a
-- base `$POSTGRES_DB`, e as variaveis de ambiente **nao** sao variaveis de psql.
-- Um `\connect :"POSTGRES_DB"` falha com `database ":POSTGRES_DB" does not exist`
-- — e, pior, falhava sem derrubar o arranque: o contentor ficava `healthy` com a
-- base sem pgvector. Verificado por execucao a 2026-10-10.
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Prova, no arranque, de que as versoes sao as que a evidencia fixa (E4 §2.9).
-- Falhar aqui e melhor do que descobrir mais tarde que a imagem mudou de minor.
DO $$
DECLARE
  v_server  text := current_setting('server_version');
  v_vector  text;
BEGIN
  SELECT extversion INTO v_vector FROM pg_extension WHERE extname = 'vector';

  IF split_part(v_server, '.', 1) <> '18' THEN
    RAISE EXCEPTION 'esperava PostgreSQL 18.x, encontrei %', v_server;
  END IF;
  IF v_vector <> '0.8.7' THEN
    RAISE EXCEPTION 'esperava pgvector 0.8.7, encontrei %', v_vector;
  END IF;

  RAISE NOTICE 'KAM-001: PostgreSQL % com pgvector % e pg_trgm', v_server, v_vector;
END
$$;
