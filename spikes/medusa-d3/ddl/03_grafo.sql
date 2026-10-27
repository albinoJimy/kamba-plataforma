-- Spike KAM-041 — o grafo de estados como **dados**, e o gatilho que o impoe.
--
-- `docs/tecnica/03_Core_Comercio_Medusa.md` §6.2: «a tabela e dados
-- (`order_state_graph(de, para)`) validados por *trigger* `BEFORE UPDATE` sobre
-- `estado`». As linhas abaixo sao as da tabela de transicoes do §6.2, sem
-- excepcao e sem acrescento.
--
-- Duas delas estao marcadas no §6.1 como **extensao proposta** e nao existem no
-- `docs/tecnica/00` §6.1: `expirada -> paga` (pagamento tardio, §6.6) e
-- `entregue -> reembolso_pendente` (disputa apos entrega). O §6.1 manda
-- implementa-las «protegidas por flag de configuracao» ate serem ratificadas.
-- Aqui ficam fora da semente por omissao, e o harness insere-as so quando
-- `KAMBA_SPIKE_EXTENSOES_PROPOSTAS=1`: um spike que as semeasse em silencio
-- estaria a medir um grafo que o canon ainda nao ratificou.

INSERT INTO platform.order_state_graph (de, para) VALUES
  ('criada',               'aguarda_pagamento'),
  ('criada',               'cancelada'),
  ('aguarda_pagamento',    'paga'),
  ('aguarda_pagamento',    'pendente_confirmacao'),
  ('aguarda_pagamento',    'expirada'),
  ('pendente_confirmacao', 'paga'),
  ('pendente_confirmacao', 'aguarda_pagamento'),
  ('expirada',             'aguarda_pagamento'),
  ('expirada',             'cancelada'),
  ('paga',                 'em_entrega'),
  ('paga',                 'entregue'),
  ('paga',                 'reembolso_pendente'),
  ('em_entrega',           'entregue');

CREATE FUNCTION platform.order_state_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  -- INSERT: a encomenda **nasce** em `criada`. O §6.2 escreve a primeira linha
  -- da tabela de transicoes como `— -> criada`, e nao ha outra entrada no
  -- grafo. Sem esta guarda, um `INSERT ... estado='paga', paga_via=NULL`
  -- entrava directamente em qualquer estado e contornava o grafo **e** a
  -- guarda do `paga_via` — e o `kamba_app` tem `INSERT` nesta tabela. O gatilho
  -- cobria so `UPDATE`, o que deixava a porta da frente aberta.
  IF TG_OP = 'INSERT' THEN
    IF NEW.estado <> 'criada' THEN
      RAISE EXCEPTION 'uma encomenda nasce em `criada`, nao em `%` (§6.2)', NEW.estado
        USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
  END IF;

  -- `UPDATE` que nao muda o estado: passa, mas **nao** se aceita a
  -- auto-transicao. `criada -> criada` nao esta no grafo do §6.2, e aceita-la
  -- gravava uma transicao inexistente no `order_state_log` e incrementava a
  -- `version` — o que pode fazer falhar o CAS de outro chamador legitimo.
  IF NEW.estado = OLD.estado THEN
    IF NEW.version <> OLD.version THEN
      RAISE EXCEPTION 'auto-transicao `% -> %` nao existe no grafo (§6.2)',
        OLD.estado, NEW.estado USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM platform.order_state_graph g
     WHERE g.de = OLD.estado AND g.para = NEW.estado
  ) THEN
    RAISE EXCEPTION 'transicao de estado nao permitida: % -> %', OLD.estado, NEW.estado
      USING ERRCODE = 'check_violation';
  END IF;
  -- §5.4 e o criterio de saida do epic: «a transicao para `paga` so e aceite
  -- com `causa.evento_id` de evento autenticado ou confirmacao manual
  -- auditada». `paga_via` e o que o registo guarda dessa causa.
  IF NEW.estado = 'paga' AND NEW.paga_via IS NULL THEN
    RAISE EXCEPTION 'transicao para `paga` exige `paga_via` (evento autenticado '
                    'ou confirmacao manual auditada)'
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END;
$$;

-- `INSERT OR UPDATE`, e nao `UPDATE OF estado`: ver a guarda do `TG_OP` na
-- funcao. `UPDATE` sem `OF estado` porque a auto-transicao tambem se verifica.
CREATE TRIGGER orders_mirror_estado_guard
  BEFORE INSERT OR UPDATE ON platform.orders_mirror
  FOR EACH ROW EXECUTE FUNCTION platform.order_state_guard();
