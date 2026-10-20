/**
 * O SQL do HND, em constantes (KAM-019).
 *
 * Constantes de módulo e não cadeias no meio do código, pela razão que o
 * KAM-015 escreveu: a suite de base de dados compara o SQL com o esquema real,
 * e uma consulta escondida numa função não se compara com nada. A prova por
 * mutação também as escolhe pelo nome.
 *
 * ## A idempotência é da base, duas vezes
 *
 * O `SQL_ABRIR_HANDOFF` e o `SQL_GUARDAR_CONTA` são os dois
 * `INSERT ... ON CONFLICT DO NOTHING RETURNING`, e os dois estão aqui pela
 * mesma razão: **um `RETURNING` vazio é a resposta**, não um erro. Significa «a
 * chave já passou», e é disso que o chamador conclui que não deve chamar o
 * terceiro. Verificar primeiro com um `SELECT` e inserir depois perdia a
 * corrida entre dois processos — e o critério 4 pede **cinco** chamadas
 * concorrentes.
 */

/**
 * Abre uma passagem. `RETURNING` vazio significa «já existia».
 *
 * O `handoff_id` vem de fora e é derivado (`hash(thread_id, ordinal)`): não há
 * `DEFAULT` a gerar nada, e é isso que faz cinco chamadas concorrentes
 * colidirem na chave em vez de criarem cinco linhas.
 *
 * Nasce em `waiting` por omissão da coluna, e sem `external_id`: a conversa no
 * provedor ainda não existe quando esta linha é escrita. **A ordem é essa de
 * propósito** — a linha antes da chamada ao terceiro, como o KAM-015 fez com o
 * envio: ao contrário, uma falha entre a criação no provedor e a escrita
 * deixava uma conversa aberta lá sem nada do nosso lado a apontar-lhe, e a
 * repetição criava outra.
 */
export const SQL_ABRIR_HANDOFF = `
  INSERT INTO platform.handoffs
         (handoff_id, tenant_id, conversation_id, motivo)
  VALUES ($1, $2, $3, $4)
      ON CONFLICT (handoff_id) DO NOTHING
   RETURNING handoff_id, status
`;

/** A passagem de um `handoff_id`, com o *tenant* no predicado para a RLS. */
export const SQL_HANDOFF_POR_ID = `
  SELECT handoff_id, tenant_id, conversation_id, status, motivo,
         external_id, opened_at, resumed_at, resolver
    FROM platform.handoffs
   WHERE tenant_id = $1 AND handoff_id = $2
`;

/**
 * Grava o identificador que o provedor devolveu, e põe a passagem em `waiting`.
 *
 * O `status = 'waiting'` não é redundante com a omissão da coluna: esta
 * instrução é também a que **recupera** uma passagem que ficou `degraded`
 * porque o provedor estava em baixo. Quando a fila a reprocessa e a conversa
 * finalmente nasce lá, é aqui que ela deixa de estar degradada.
 *
 * O `WHERE status = ANY($4)` impede que isto reabra uma passagem já concluída:
 * se o `resolved` chegou antes de a fila drenar, o `UPDATE` não casa e o
 * `external_id` fica por gravar — o que é o lado certo para errar, porque a
 * alternativa é ressuscitar um handoff fechado.
 */
export const SQL_MARCAR_ABERTA = `
  UPDATE platform.handoffs
     SET external_id = $3, status = 'waiting'
   WHERE tenant_id = $1
     AND handoff_id = $2
     AND status = ANY($4::text[])
   RETURNING handoff_id, status
`;

/**
 * Marca a passagem como degradada: aberta do nosso lado, não do dele.
 *
 * Só sai de `waiting`, e não de um estado concluído: uma passagem que já
 * fechou não volta a degradar-se por o provedor ter ficado em baixo depois.
 */
export const SQL_MARCAR_DEGRADADA = `
  UPDATE platform.handoffs
     SET status = 'degraded'
   WHERE tenant_id = $1
     AND handoff_id = $2
     AND status = 'waiting'
   RETURNING handoff_id, status
`;

/**
 * Fecha a passagem, com a monotonia **no predicado**.
 *
 * O `$4` é a lista dos estados de que se pode fechar (`estados.ts`), e é ela
 * que faz do `resolved` duplicado um *no-op* **pela base**: o segundo `UPDATE`
 * não casa e devolve zero linhas. É a mesma técnica da monotonia da saída no
 * KAM-015, e pela mesma razão — dois *webhooks* duplicados chegam a dois
 * processos, e só a base os serializa.
 *
 * O `resumed_at` escreve-se **apenas** quando o estado novo é `resumed`, e é a
 * única coluna desta revisão que o KAM-034 vai querer: o critério 7 põe o
 * *compare-and-set* da retoma lá, e o que fica aqui é o que o `close` sabe.
 *
 * **O *tenant* vem do contexto da sessão e não de um parâmetro**, e é a única
 * consulta deste módulo assim. A razão é a assinatura: o `close(handoffId,
 * outcome)` do `docs/tecnica/01` §11.1 **não tem** `tenantId`, e inventar-lhe
 * um terceiro argumento era alterar a costura que o ADR-012 fixa. Quando um
 * `close` corre, o contexto já está posto — ele vem de um *callback* cuja
 * conta foi resolvida —, e o `current_setting` é exactamente o que a política
 * `tenant_iso` já lê. O predicado explícito é redundante com a RLS de
 * propósito: se alguém desligar o `FORCE` por engano, esta consulta continua a
 * não atravessar *tenants*.
 */
export const SQL_FECHAR = `
  UPDATE platform.handoffs
     SET status = $2,
         resumed_at = CASE WHEN $2 = 'resumed' THEN now() ELSE resumed_at END,
         resolver = COALESCE($4, resolver)
   WHERE tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
     AND handoff_id = $1
     AND status = ANY($3::text[])
   RETURNING handoff_id, status
`;

/**
 * Guarda a conta de atendimento. `RETURNING` vazio significa «já existia».
 *
 * É este `ON CONFLICT` que torna o critério 1 uma propriedade da **base**:
 * «`ensureAccount` chamado 2× não duplica» não depende de o código verificar
 * primeiro, depende de a chave `(tenant_id, provedor)` existir.
 */
export const SQL_GUARDAR_CONTA = `
  INSERT INTO platform.handoff_accounts
         (tenant_id, provedor, account_id, inbox_id, bot_id, token_ref)
  VALUES ($1, $2, $3, $4, $5, $6)
      ON CONFLICT (tenant_id, provedor) DO NOTHING
   RETURNING tenant_id, account_id, inbox_id, bot_id
`;

/** A conta de atendimento de um *tenant*. */
export const SQL_CONTA = `
  SELECT tenant_id, provedor, account_id, inbox_id, bot_id, token_ref
    FROM platform.handoff_accounts
   WHERE tenant_id = $1 AND provedor = $2
`;

/**
 * Repõe os identificadores de uma conta que o provedor recriou.
 *
 * O `ensureAccount` «repõe» uma conta em falta (`docs/tecnica/01` §11.5), e é
 * esta instrução que o grava. **Não** toca no `account_id`: uma conta no
 * provedor não muda de identidade, e se mudar é uma conta nova — que bate na
 * `handoff_accounts_conta_uq` em vez de sobrescrever a antiga em silêncio.
 */
export const SQL_REPOR_CONTA = `
  UPDATE platform.handoff_accounts
     SET inbox_id = $3, bot_id = $4, token_ref = $5, updated_at = now()
   WHERE tenant_id = $1 AND provedor = $2
   RETURNING tenant_id, account_id, inbox_id, bot_id
`;

/**
 * As passagens que passaram do SLA de retoma, por *tenant*.
 *
 * O `docs/tecnica/02` §11 fixa «SLA < 15 min por tenant», e esta é a consulta
 * que o painel lê. Usa o índice `(tenant_id, opened_at DESC)` que a revisão
 * `0011` acrescentou — que existe primeiro por causa da RLS e só depois por
 * causa desta consulta, mas a segunda coluna é escolha dela.
 *
 * `degraded` entra na contagem: uma passagem que nem chegou ao provedor está
 * tão longe de ser atendida como uma à espera, e esconder-lhe o atraso era
 * mostrar um painel verde no pior caso.
 */
export const SQL_FORA_DO_SLA = `
  SELECT handoff_id, status, opened_at
    FROM platform.handoffs
   WHERE tenant_id = $1
     AND status IN ('waiting', 'degraded')
     AND opened_at < now() - $2::interval
   ORDER BY opened_at DESC
`;
