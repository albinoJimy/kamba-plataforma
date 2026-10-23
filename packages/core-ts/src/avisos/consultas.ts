/**
 * O SQL do aviso ao dono (KAM-115).
 *
 * Em constantes e num módulo só, pela razão que o `outbound/consultas.ts` do
 * KAM-015 e o `qualidade/consultas.ts` do KAM-021 escreveram: a *suite* do
 * *gate* 8 corre **estas** cadeias e não cópias delas, e foi assim que o KAM-009
 * descobriu um `coalesce` em falta que uma cópia no teste escondia.
 *
 * ## Tudo parametrizado, e o `tenant_id` no predicado além da RLS
 *
 * O módulo corre como `kamba_app`, sujeito à RLS, mas um processo de retaguarda
 * pode chamá-lo com outro papel — e **neste módulo isso não é hipótese**: as
 * varreduras dos lembretes correm como `kamba_batch`, que tem `BYPASSRLS`. O
 * `tenant_id` está no predicado **além** da política pela razão do `SQL_JANELA`
 * do KAM-015: ela já o garante, e repeti-lo é o que torna a consulta correcta
 * mesmo corrida sem contexto — devolve zero linhas em vez do aviso de outro.
 *
 * As duas consultas que **não** levam `tenant_id` levam-no de propósito e
 * dizem-no: a varredura dos lembretes e a dos tenants sem contacto verificado
 * são de todos os tenants, porque um lembrete que venceu não é problema de uma
 * loja. São as únicas, e só correm sob `BYPASSRLS`.
 */

/**
 * O histórico de avisos de um tenant nas últimas 24 h.
 *
 * **Todos os gatilhos**, porque o tecto diário do critério 4 precisa de os ver
 * todos; o filtro por gatilho faz-se no `decidir`, que é onde a regra está
 * escrita. Trazer só o gatilho pedido fazia o tecto diário contar um quinto do
 * que devia.
 *
 * O intervalo é parâmetro e não `interval '24 hours'`: o critério 4 manda medir
 * com relógio acelerado, e um intervalo literal na consulta não se acelera sem
 * mexer no servidor. É a mesma escolha que a `0018` fez ao pôr o `prazo_em` numa
 * coluna.
 */
export const SQL_HISTORICO = `
  SELECT id, tenant_id, gatilho, episodio, lembrete, canal, estado,
         tentativas, falha_motivo, criado_at, entregue_at
    FROM platform.owner_notices
   WHERE tenant_id = $1
     AND criado_at > $2
   ORDER BY criado_at DESC
`;

/**
 * Escreve o aviso, e **deixa-o passar em silêncio se já existir**.
 *
 * `ON CONFLICT DO NOTHING` sobre a `owner_notices_idempotencia_uq`, e é isto o
 * critério 2 inteiro: três entregas do mesmo evento tentam escrever a mesma
 * linha e fica uma. O `RETURNING` devolve zero linhas na segunda passagem — quem
 * chama sabe pelo número de linhas se escreveu, e não por uma leitura anterior
 * que uma corrida podia invalidar entre a leitura e a escrita.
 *
 * **E o `criado_at` vem do relógio de quem chama, não do `now()` do servidor.**
 * Era `DEFAULT now()` na primeira versão, e o primeiro ensaio contra a base
 * mostrou o que isso custava: os dois limites do critério 4 e os lembretes
 * medem-se **deste** carimbo, e com ele escrito pelo servidor um relógio
 * acelerado nos testes media uma coisa e a base registava outra — a varredura
 * dos lembretes não via nenhum episódio, porque as linhas tinham a hora real e
 * a janela tinha a hora do ensaio. É a mesma razão pela qual o `prazo_em` da
 * `0018` é coluna e não cálculo: «um prazo derivado de `now()` na consulta não
 * se acelera sem mexer no servidor». O `DEFAULT now()` fica na tabela para quem
 * insira à mão e para a semente do *gate* 6.
 *
 * **O `estado` nasce `pendente` e não `entregue`**, mesmo quando a entrega é
 * síncrona e corre a seguir. A ordem é registar-depois-entregar e não o
 * contrário, pela razão que o `outbound` do KAM-015 escreveu: se o processo cair
 * entre as duas, um aviso registado que não saiu descobre-se na varredura dos
 * pendentes, e um aviso entregue que não se registou volta a sair — e o dono
 * recebe dois.
 */
export const SQL_REGISTAR = `
  INSERT INTO platform.owner_notices
         (tenant_id, gatilho, episodio, chave, lembrete, canal,
          criado_at, actualizado_at)
  VALUES ($1, $2, $3, $4, $5, $6, $7, $7)
      ON CONFLICT (tenant_id, chave, lembrete, canal) DO NOTHING
   RETURNING id, tenant_id, gatilho, episodio, lembrete, canal, estado,
             tentativas, falha_motivo, criado_at, entregue_at
`;

/**
 * Marca um aviso como entregue.
 *
 * O predicado tem `estado = 'pendente'`, e não é zelo: sem ele, uma segunda
 * confirmação do fornecedor movia o `entregue_at` para a frente e a latência do
 * critério 3 passava a medir a confirmação mais recente em vez da primeira
 * entrega. Com ele, a segunda passagem devolve zero linhas.
 */
export const SQL_ENTREGUE = `
  UPDATE platform.owner_notices
     SET estado = 'entregue',
         entregue_at = $3,
         tentativas = tentativas + 1,
         actualizado_at = $3
   WHERE tenant_id = $1
     AND id = $2
     AND estado = 'pendente'
   RETURNING id, tenant_id, gatilho, episodio, lembrete, canal, estado,
             tentativas, falha_motivo, criado_at, entregue_at
`;

/**
 * Marca um aviso como falhado.
 *
 * Sem `estado = 'pendente'` no predicado, ao contrário do `SQL_ENTREGUE`, e a
 * assimetria é de propósito: uma entrega pode falhar **depois** de uma primeira
 * falha — é o que a coluna `tentativas` conta —, e um aviso já `falhado` que
 * volte a falhar deve actualizar o motivo. O que não pode é um aviso `entregue`
 * passar a `falhado`, e é isso que o `estado <> 'entregue'` impede.
 */
export const SQL_FALHOU = `
  UPDATE platform.owner_notices
     SET estado = 'falhado',
         falha_motivo = $3,
         tentativas = tentativas + 1,
         actualizado_at = $4
   WHERE tenant_id = $1
     AND id = $2
     AND estado <> 'entregue'
   RETURNING id, tenant_id, gatilho, episodio, lembrete, canal, estado,
             tentativas, falha_motivo, criado_at, entregue_at
`;

/**
 * O contacto alternativo de um tenant, por canal.
 *
 * Traz o inválido também, e isso é decisão: quem chama precisa de distinguir
 * «não há endereço» de «há e está condenado», porque os dois levam a coisas
 * diferentes — o primeiro é o `sem_contacto` do critério 6 (alerta a T2 e
 * `owner_alt_contact_missing`), o segundo é o critério 7 a ter já actuado, e
 * abrir outra tarefa por ele era abrir uma tarefa por cada aviso que não sai.
 */
export const SQL_CONTACTO = `
  SELECT id, tenant_id, canal, endereco_enc, verificado_at,
         invalido_at, motivo_invalido
    FROM platform.owner_contacts
   WHERE tenant_id = $1
     AND canal = $2
`;

/**
 * Marca o contacto como inválido (critério 7).
 *
 * `WHERE invalido_at IS NULL`, e isto guarda o **primeiro** motivo e o primeiro
 * instante. Sem o predicado, um segundo *bounce* reescrevia a data e a pergunta
 * «desde quando é que este dono está sem canal?» mudava de resposta a cada
 * tentativa.
 */
export const SQL_INVALIDAR = `
  UPDATE platform.owner_contacts
     SET invalido_at = $4,
         motivo_invalido = $3,
         actualizado_at = $4
   WHERE tenant_id = $1
     AND canal = $2
     AND invalido_at IS NULL
   RETURNING id, tenant_id, canal, endereco_enc, verificado_at,
             invalido_at, motivo_invalido
`;

/**
 * Emite a ligação de confirmação: guarda o resumo do *token* e o prazo.
 *
 * **Repõe o `verificado_at` a nulo**, e é o ponto mais fácil de errar deste
 * ficheiro: emitir uma confirmação nova é dizer que o endereço ainda não está
 * provado. Sem esta reposição, um endereço trocado herdava a verificação do
 * anterior — e o critério 6 passava a dizer que um e-mail que ninguém confirmou
 * está confirmado.
 *
 * E repõe a invalidez: um endereço que se volta a confirmar deixa de estar
 * condenado, que é como o dono sai do estado em que o critério 7 o pôs.
 */
export const SQL_EMITIR_CONFIRMACAO = `
  UPDATE platform.owner_contacts
     SET confirmacao_hash = $3,
         confirmacao_expira_em = $4,
         verificado_at = NULL,
         invalido_at = NULL,
         motivo_invalido = NULL,
         actualizado_at = $5
   WHERE tenant_id = $1
     AND canal = $2
   RETURNING id, tenant_id, canal, endereco_enc, verificado_at,
             invalido_at, motivo_invalido
`;

/**
 * Confirma o endereço, se o resumo e o prazo baterem.
 *
 * **A comparação é na base e não no código**, e isso é o que faz a confirmação
 * ser atómica: com a leitura e a escrita separadas, duas confirmações
 * simultâneas do mesmo *token* passavam as duas. E o `confirmacao_expira_em >
 * $4` põe o prazo no predicado — um `token` expirado não confirma nada, e quem o
 * decide é o PostgreSQL com o instante que lhe passamos (o relógio acelerado dos
 * ensaios).
 *
 * Apaga o resumo ao confirmar: um *token* já usado não se reutiliza, e deixá-lo
 * na coluna era deixar uma ligação eterna à espera de quem a encontrasse num
 * e-mail antigo.
 */
export const SQL_CONFIRMAR = `
  UPDATE platform.owner_contacts
     SET verificado_at = $4,
         confirmacao_hash = NULL,
         confirmacao_expira_em = NULL,
         actualizado_at = $4
   WHERE tenant_id = $1
     AND canal = $2
     AND confirmacao_hash = $3
     AND confirmacao_expira_em > $4
   RETURNING id, tenant_id, canal, endereco_enc, verificado_at,
             invalido_at, motivo_invalido
`;

/**
 * Os episódios cujo lembrete está devido (critério 4).
 *
 * **Sem `tenant_id`**: um lembrete que venceu não é problema de uma loja, e esta
 * consulta só corre sob `BYPASSRLS` (`kamba_batch`). É a mesma escolha que as
 * varreduras do KAM-016, do KAM-018 e do KAM-017 fizeram, e o índice
 * `owner_notices_pendentes_idx` é parcial por isso.
 *
 * O agrupamento é por `(tenant_id, chave)` — o episódio — e traz o **primeiro**
 * aviso, que é de onde o relógio dos lembretes conta, mais o maior lembrete já
 * enviado. Sem o segundo, a varredura não distinguia «ainda não mandei nenhum»
 * de «já mandei os dois», e os dois casos levam a coisas opostas.
 *
 * **E o `HAVING` é `<=` e não `<`.** Com `<`, um episódio que já levou o último
 * lembrete **desaparecia** da varredura — e com ele desaparecia o «depois pára e
 * abre tarefa a T2» do critério 4, que ficava sem caminho executável: só decisão
 * escrita. Com `<=`, o episódio esgotado aparece, o `lembretesEsgotados`
 * reconhece-o e a tarefa abre. Achado da revisão adversarial deste ticket, e é a
 * mesma classe do que a revisão adversarial da `0018` encontrou nas concessões
 * ao `kamba_batch`.
 */
export const SQL_EPISODIOS_PARA_LEMBRETE = `
  SELECT tenant_id, chave, gatilho, episodio,
         min(criado_at)   AS primeiro_em,
         max(lembrete)    AS ultimo_lembrete
    FROM platform.owner_notices
   WHERE criado_at > $1
   GROUP BY tenant_id, chave, gatilho, episodio
  HAVING max(lembrete) <= $2
   ORDER BY min(criado_at)
`;

/**
 * Os tenants `ativo` sem nenhum contacto alternativo verificado (critério 6).
 *
 * **Sem `tenant_id`** e com `LEFT JOIN`: a pergunta é «quais os tenants que
 * estão em risco de não poder ser avisados», e é por isso que ela se faz por
 * ausência. Só corre sob `BYPASSRLS`.
 *
 * O `estado = 'ativo'` é literal do critério, e é o que impede a varredura de
 * reclamar dos tenants em `onboarding` — que, por definição, ainda não deram
 * e-mail nenhum. O domínio é o `CHECK` da `0001`.
 */
export const SQL_TENANTS_SEM_CONTACTO = `
  SELECT t.id
    FROM platform.tenants AS t
    LEFT JOIN platform.owner_contacts AS c
           ON c.tenant_id = t.id
          AND c.verificado_at IS NOT NULL
          AND c.invalido_at IS NULL
   WHERE t.estado = 'ativo'
     AND c.id IS NULL
   ORDER BY t.id
`;

/**
 * O nome da loja, para o parâmetro `loja` dos modelos.
 *
 * Uma consulta só para isto, e não um `JOIN` nas outras: o nome só se lê quando
 * há aviso para construir, e lê-lo em toda a decisão era trazer o nome da loja
 * para dentro de caminhos que o recusam — a decisão de **não** avisar não precisa
 * de saber o nome de ninguém.
 */
export const SQL_NOME_DA_LOJA = `
  SELECT nome
    FROM platform.tenants
   WHERE id = $1
`;

/**
 * Quantos tenants estão `ativo`.
 *
 * O denominador da percentagem do critério 6 («≥ 95% dos tenants `ativo` com
 * contacto verificado»). **Sem `tenant_id`**, pela mesma razão das duas
 * varreduras acima, e por isso só corre sob `BYPASSRLS`.
 */
export const SQL_TENANTS_ATIVOS = `
  SELECT count(*)::int AS quantos
    FROM platform.tenants
   WHERE estado = 'ativo'
`;
