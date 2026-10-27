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

/**
 * O `contact_id` da conversa desta passagem, para montar o `thread_id`.
 *
 * **Existe porque o `handoff_id` é irreversível.** Ele é
 * `sha256(thread_id:handoff_seq)` (§3.15), pelo que do identificador não se lê o
 * *thread* de volta — e o corpo de `/internal/resume` é
 * `{thread_id, handoff_id, outcome}`, com o `thread_id` a ser
 * `{tenant_id}:{contact_id}` (§3.1). O `tenant_id` o HND já tem (é a conta que
 * resolveu o *callback*); o `contact_id` está na conversa a que a passagem
 * aponta, e esta é a instrução que o traz.
 *
 * **O `external_id` sai no `SELECT` e NÃO vai no predicado, e isso é a correcção
 * de um defeito que a revisão adversarial mediu.** A primeira versão punha
 * `AND h.external_id = $3`, com esta justificação:
 *
 * > «Uma passagem `degraded` tem `external_id` nulo e por isso nunca casa aqui,
 * > o que é o lado certo: ela não existe no provedor, logo nenhum *callback*
 * > legítimo dele pode ser dela.»
 *
 * **A premissa é falsa, e o `chatwoot.ts` di-lo em dez linhas:** o
 * `abrirConversa` **cria** a conversa no provedor, com o atributo `handoffId`, e
 * só **depois** publica a nota privada. Se a nota levar um 5xx ou esgotar o
 * tecto, o `openHandoff` apanha `ProvedorIndisponivelError` e marca a passagem
 * `degraded` com `external_id` a `NULL` — **e a conversa está aberta lá, com o
 * atributo**. Um colega resolve-a, o *callback* chega, e com o `external_id` no
 * predicado dava zero linhas: nenhum pedido de retoma, nenhuma escrita, um 200
 * ao provedor (que pára de reenviar) e o `interrupt()` pendente para sempre —
 * que é, letra por letra, o defeito que a emenda 1.42 existe para matar. E
 * invisível: a varredura dos prazos filtra `waiting` e esta ficava `degraded`,
 * e o *job* `abertura:` que escreveria o `external_id` não tem consumidor neste
 * repositório. A mesma coisa, por 24 h em vez de para sempre, na janela entre o
 * `INSERT` e o `SQL_MARCAR_ABERTA`, que é uma chamada HTTP a um terceiro.
 *
 * Por isso a coluna **sai no `SELECT`** e quem decide é o chamador, com três
 * saídas distinguíveis em vez de um zero para tudo (ver `#retomarAPassagem`):
 * a conversa bate, a nossa linha ainda não tem conversa gravada (recupera-se com
 * o `SQL_MARCAR_ABERTA`, que é a instrução que já existe para isso), ou o
 * atributo é de **outra** conversa — e essa é a única que se recusa.
 *
 * **A verificação que o `external_id` compra continua a ser a razão de ele sair
 * daqui**, e é a que fecha deste lado o buraco que o §3.32 nomeia do outro: o
 * `handoff_id` chega-nos do atributo de uma conversa **no provedor**, isto é, de
 * fora, e um valor trocado lá — um `handoff_id` do mesmo *tenant* e de **outro
 * contacto** — passa o `tenant_id` e faz-nos pedir a retoma do *thread* errado,
 * isto é, a conversa de outra pessoa com o desfecho desta.
 *
 * O AGR faz a verificação equivalente pelo outro lado (o `contact_id` no
 * predicado do CAS) e as duas não são redundantes: a dele impede que **alguém**
 * retome o *thread* errado, a nossa impede que **nós** lho peçamos — e sem a
 * nossa, o pedido chegava lá e saía como `recusado` (404), que é um alerta sobre
 * um defeito nosso disfarçado de ataque.
 *
 * Parâmetros: o `tenant_id` e o `handoff_id`.
 */
export const SQL_THREAD_DA_PASSAGEM = `
  SELECT c.contact_id, h.external_id
    FROM platform.handoffs h
    JOIN platform.conversations c
      ON c.tenant_id = h.tenant_id
     AND c.id = h.conversation_id
   WHERE h.tenant_id = $1
     AND h.handoff_id = $2
`;

/**
 * Escreve o `resolver`, e **só** o `resolver`.
 *
 * **Nasce porque o `#fechar` deixou de escrever.** Até à emenda 1.42 o
 * identificador do agente viajava no `SQL_FECHAR`, na mesma instrução que punha
 * o `status` em `resumed`; com a transição a passar a ser do AGR, essa instrução
 * já não corre no caminho `resolved` e o `resolver` ficava por escrever em
 * caminho nenhum. E não pode ir no corpo da retoma: o ADR-010 mantém a
 * identidade do agente fora do AGR, e a linha «Corpo da retoma interna» do
 * §3.32 di-lo por extenso — «quem sabe que agente respondeu é o HND, e o AGR
 * nunca aprende essa identidade». Logo, escrita separada, deste lado.
 *
 * **O `status = 'waiting'` no predicado torna o *webhook* duplicado um *no-op*
 * também aqui — no duplicado SEQUENCIAL, e a distinção é medida.** O segundo
 * *callback* que chegue depois de o CAS ter movido a linha não casa, e **não
 * reescreve** o `resolver` de quem de facto respondeu; sem o predicado, passava
 * por cima dele, e nos dois *webhooks* do Chatwoot o segundo pode trazer outro
 * `assignee`.
 *
 * **Duas chegadas concorrentes escrevem as duas**, e a nota dizia o contrário —
 * achado da revisão adversarial. Elas vêem ambas `status = 'waiting'`, os dois
 * `UPDATE` casam, e vence o último; o CAS do AGR continua a dar **uma** retoma,
 * mas o `resolver` pode ficar o do segundo. Não se fecha com um
 * `resolver IS NULL` no predicado, e a razão é a de baixo: ele faria o caminho
 * **normal** da repetição legítima devolver zero linhas. O que se perde é
 * pequeno e nomeia-se: os dois valores são agentes do mesmo *tenant* a resolver
 * a mesma conversa nos mesmos milissegundos, pelo que «quem respondeu» é
 * ambíguo de facto e não só na coluna.
 *
 * **E não leva `resolver IS NULL`**, que era o que apetecia para ficar
 * «primeiro a escrever vence». A razão é a repetição legítima: um 503 do AGR faz
 * o provedor reenviar o *callback*, e nessa segunda volta a passagem ainda está
 * em `waiting` — com `resolver IS NULL` a instrução passava a devolver zero
 * linhas no caminho **normal**, e um zero que é normal é um zero que não se pode
 * vigiar. Quem exclui o segundo agente é o `status`, não esta coluna.
 *
 * O chamador só a corre quando o *callback* **traz** o identificador: um
 * `COALESCE($3, resolver)` punha a instrução a correr para nada e a devolver uma
 * linha a dizer que escreveu.
 *
 * Parâmetros: o `tenant_id`, o `handoff_id` e o `resolver`.
 */
export const SQL_MARCAR_RESOLVER = `
  UPDATE platform.handoffs
     SET resolver = $3
   WHERE tenant_id = $1
     AND handoff_id = $2
     AND status = 'waiting'
   RETURNING handoff_id
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
 * Fecha a passagem, com a monotonia **no predicado**. Só de `degraded`.
 *
 * O `$3` é a lista dos estados de que se pode fechar (`estados.ts`), e é ela
 * que faz do `close` repetido um *no-op* **pela base**: o segundo `UPDATE`
 * não casa e devolve zero linhas. É a mesma técnica da monotonia da saída no
 * KAM-015, e pela mesma razão — dois *webhooks* duplicados chegam a dois
 * processos, e só a base os serializa.
 *
 * **A lista deixou de ter `waiting`, e isso muda o que esta instrução é.** Até à
 * emenda 1.42 ela era o segundo escritor da transição `waiting → resumed`, e
 * corria **antes** de o AGR ter a oportunidade de a escrever — o que fazia do
 * *compare-and-set* dele um *no-op* e deixava o `interrupt()` do `handoff_wait`
 * pendente para sempre (`docs/analises/ANALISE-35`, achado 1). Hoje a saída de
 * `waiting` é toda do AGR, por `/internal/resume`, e o que fica aqui é o fecho
 * de uma passagem **`degraded`** — a que nunca chegou ao provedor, e que o
 * predicado do CAS dele recusa. Ver a nota do `ESTADOS_QUE_FECHAM`.
 *
 * O `resumed_at` escreve-se **apenas** quando o estado novo é `resumed`, e o
 * AGR escreve-o nos três desfechos: a divergência está medida e escrita no
 * §3.32, e sobrevive só neste caminho — o `degraded`, de que ele não fecha.
 *
 * **O *tenant* vem do contexto da sessão e não de um parâmetro**, e é a única
 * consulta deste módulo assim. A razão é a assinatura: o `close(handoffId,
 * outcome)` do `docs/tecnica/01` §11.1 **não tem** `tenantId`, e inventar-lhe
 * um terceiro argumento era alterar a costura que o ADR-012 fixa. Quando um
 * `close` corre, o contexto já está posto — ele vem de um *callback* cuja
 * conta foi resolvida —, e o `current_setting` é exactamente o que a política
 * `tenant_iso` já lê.
 *
 * **O `current_setting` é a forma estrita, sem o segundo argumento, e isso é a
 * correcção de um defeito.** A primeira versão usava
 * `current_setting('app.tenant_id', true)`, que devolve `NULL` quando a
 * variável não está definida: `tenant_id = NULL` não é verdadeiro para linha
 * nenhuma, pelo que um `close` sem contexto de sessão não casava nada **em
 * silêncio** — zero linhas, nenhuma métrica, nenhum registo, e um 200 ao
 * provedor, que pára de reenviar. A passagem ficava em `waiting` para sempre e
 * aparecia no painel do SLA como atrasada, sem um único sinal de que o fecho se
 * tinha perdido. A forma estrita **levanta** `42704`, e uma excepção é o que se
 * quer: ou o contexto está posto, ou isto não corre.
 *
 * **E o `resolver` saiu daqui**, com o `$4` e o `COALESCE` que o levava. Ele
 * tem instrução própria (`SQL_MARCAR_RESOLVER`) desde a emenda 1.42, e o único
 * chamador que lhe passava um valor era o caminho `resolved` do `receber`, que
 * deixou de fechar. Um `COALESCE($4, resolver)` que recebe `null` em todas as
 * chamadas é a mesma classe de coisa que o `SQL_REPOR_CONTA` que este ficheiro
 * já retirou por não ter chamador — um pedaço de instrução para um caminho
 * inexistente, que o próximo leitor toma por caminho existente.
 *
 * **E o que a primeira versão dizia sobre o `FORCE` era falso**, pelo que sai:
 * o predicado é byte a byte o que a política `tenant_iso` gera, e o `FORCE` só
 * vincula o **dono** da tabela — o `kamba_app`, que corre esta consulta, está
 * sujeito à política com `ENABLE` simples. O predicado explícito não acrescenta
 * uma segunda fechadura; o que ele acrescenta é a **mensagem de erro**, que
 * aponta para o contexto em falta em vez de devolver um zero.
 */
export const SQL_FECHAR = `
  UPDATE platform.handoffs
     SET status = $2,
         resumed_at = CASE WHEN $2 = 'resumed' THEN now() ELSE resumed_at END
   WHERE tenant_id = NULLIF(current_setting('app.tenant_id'), '')::uuid
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
         (tenant_id, provedor, account_id, inbox_id, bot_id,
          provider_user_id, token_ref, user_token_ref)
  VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
      ON CONFLICT (tenant_id, provedor) DO NOTHING
   RETURNING tenant_id, account_id, inbox_id, bot_id, provider_user_id
`;

/**
 * A conta de atendimento de um *tenant*.
 *
 * **As duas referências de segredo saem no `SELECT` e o `provider_user_id`
 * entra**, pela emenda 1.23: os *endpoints* da conta querem o *token* do
 * utilizador e os da conversa o do bot, e quem chama precisa de saber por qual
 * pedir ao cofre. As colunas são `SecretRef` opacas — o que sai daqui não é um
 * *token*, é a referência por onde se vai buscar um.
 */
export const SQL_CONTA = `
  SELECT tenant_id, provedor, account_id, inbox_id, bot_id,
         provider_user_id, token_ref, user_token_ref
    FROM platform.handoff_accounts
   WHERE tenant_id = $1 AND provedor = $2
`;

/*
 * **Aqui estava o `SQL_REPOR_CONTA`, e sai porque não tinha chamador.**
 *
 * O docstring dizia «o `ensureAccount` «repõe» uma conta em falta
 * (`docs/tecnica/01` §11.5), e é esta instrução que o grava» — e o
 * `ensureAccount` faz `SELECT`, `criarConta` e `INSERT`, e mais nada. Uma
 * instrução sem chamador é código morto; o que a tornava pior é que a revisão
 * `0011` concedia `GRANT UPDATE` em `handoff_accounts` a `kamba_app` **para
 * ela**, o que é um privilégio de escrita aberto para um caminho inexistente —
 * exactamente o que a `0009` recusou por escrito.
 *
 * A reposição do `01` §11.5 **não está implementada no KAM-019**, e fica dito.
 * Quem a fizer acrescenta a instrução, o `GRANT` e o chamador no mesmo diff.
 */

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
