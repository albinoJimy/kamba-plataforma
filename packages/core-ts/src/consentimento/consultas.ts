/**
 * O SQL do consentimento (KAM-022).
 *
 * Em constantes e num módulo só, pela razão que o `outbound/consultas.ts` do
 * KAM-015 e o `qualidade/consultas.ts` do KAM-021 escreveram: a *suite* do
 * *gate* 8 corre **estas** cadeias e não cópias delas, e foi assim que o KAM-009
 * descobriu um `coalesce` em falta que uma cópia no teste escondia.
 *
 * ## Tudo parametrizado, e o `tenant_id` no predicado além da RLS
 *
 * O módulo corre como `kamba_app`, sujeito à RLS, mas um processo de retaguarda
 * pode chamá-lo com outro papel; o `tenant_id` está no predicado **além** da
 * política pela razão do `SQL_JANELA` do KAM-015: ela já o garante, e repeti-lo
 * é o que torna a consulta correcta mesmo corrida sem contexto — devolve zero
 * linhas em vez das de outro.
 *
 * **A `consent_texts` é a excepção, e é a única.** Ela não tem `tenant_id` — é
 * um texto jurídico de plataforma — pelo que a consulta dela não leva nenhum, e
 * não há política a repetir. Fica dito aqui para que a ausência se leia como
 * decisão e não como esquecimento.
 */

/**
 * A versão vigente do aviso para uma finalidade.
 *
 * Parâmetros: `$1` a finalidade, `$2` o instante (`NULL` para `now()`).
 *
 * «Vigente» é a de `vigente_desde` mais alto que **já passou**: uma versão
 * publicada com data futura não vigora, e é assim que se publica um texto novo
 * antes de ele valer. O `LIMIT 1` sobre o `ORDER BY ... DESC` é o índice
 * `consent_texts_vigente_idx` a responder.
 *
 * **Zero linhas é um caso real e não um erro de programação:** a `0015` cria a
 * tabela **vazia**, porque o texto está «a confirmar por parecer» (KAM-104).
 * Quem lê trata a ausência como falha fechada — sem aviso para mostrar, não há
 * consentimento a registar e o AGR não corre.
 */
export const SQL_TEXTO_VIGENTE = `
  SELECT version, texto
    FROM platform.consent_texts
   WHERE purpose = $1
     AND vigente_desde <= coalesce($2, now())
   ORDER BY vigente_desde DESC
   LIMIT 1
`;

/**
 * O estado corrente do consentimento de um contacto para uma finalidade.
 *
 * Parâmetros: `$1` o *tenant*, `$2` o contacto, `$3` a finalidade.
 *
 * Lê a **vista** `consent_actual` e não a tabela, e isso é o critério 6: «a
 * vista `consent_actual` devolve o último estado por `(tenant, contact,
 * purpose)`». Ler a tabela com um `ORDER BY ... LIMIT 1` dava o mesmo resultado
 * e punha a regra do «último» em dois sítios — e é a vista que a define.
 *
 * A vista leva `security_invoker = true`, pelo que a RLS é a de quem consulta.
 * Sem essa opção, uma vista corre com os privilégios do dono e o isolamento
 * passava a depender do `FORCE` — numa relação onde ninguém iria procurar.
 */
export const SQL_ESTADO = `
  SELECT accepted, text_version
    FROM platform.consent_actual
   WHERE tenant_id = $1 AND contact_id = $2 AND purpose = $3
`;

/**
 * Registra a prova, e **não faz nada** se a mesma prova já passou.
 *
 * Parâmetros: `$1` o *tenant*, `$2` o contacto, `$3` a finalidade, `$4` a versão
 * do texto, `$5` o `accepted`, `$6` o canal, `$7` o resumo, `$8` a hora da Meta
 * (`NULL` para `now()`).
 *
 * ## A idempotência do critério 2 é da base, e o `RETURNING` vazio é o sinal
 *
 * `ON CONFLICT (tenant_id, contact_id, purpose, evidence_hash) DO NOTHING
 * RETURNING id`: o `RETURNING` vazio significa «esta prova já está registada».
 * Não há `SELECT` antes do `INSERT` — entre os dois cabe outro processo, e o
 * critério pede **uma** linha, não «quase sempre uma».
 *
 * O que torna isto suficiente é a composição do resumo: o `wamid` e a hora são
 * **da Meta**, pelo que uma reentrega do mesmo *webhook* produz o mesmo valor.
 * Ver `prova.ts`.
 *
 * **A revogação é uma linha nova e não um `UPDATE`**, e não é por escolha de
 * estilo: a `0015` não concede `UPDATE` a `kamba_app`. O critério 6 e o
 * privilégio dizem a mesma coisa, e o privilégio é o que a prende.
 */
export const SQL_REGISTAR = `
  INSERT INTO platform.consent_event
         (tenant_id, contact_id, purpose, text_version, accepted, canal,
          evidence_hash, ocorrido_em)
  VALUES ($1, $2, $3, $4, $5, $6, $7, coalesce($8, now()))
      ON CONFLICT (tenant_id, contact_id, purpose, evidence_hash) DO NOTHING
   RETURNING id
`;

/**
 * Quantos avisos já saíram nesta conversa (critério 3).
 *
 * Parâmetros: `$1` o *tenant*, `$2` a conversa, `$3` o padrão da chave.
 *
 * ## A contagem sai da chave de idempotência, e não de uma coluna nova
 *
 * «Texto livre em vez de botão repete o aviso até 2 vezes e depois encaminha a
 * `humano`.» Isso precisa de saber quantos avisos já foram enviados — e não há
 * coluna para isso em sítio nenhum do esquema.
 *
 * A alternativa óbvia era criar uma: uma coluna `avisos_enviados` em
 * `conversations`, que o KAM-018 teria de aprender a não mexer, ou uma tabela de
 * contagem. A que se escolheu não acrescenta DDL: o aviso sai com uma
 * `idempotency_key` que **nós** derivamos,
 * `aviso:{conversation_id}:{n}`, e contá-las é um `count(*)` com prefixo. A
 * mesma chave que impede o aviso de sair duas vezes é a que diz quantas vezes
 * saiu.
 *
 * O prefixo entra como **parâmetro** e não interpolado, e o `LIKE` resolve-se
 * pelo índice `outbound_messages_idempotency_uq`, que é
 * `(tenant_id, idempotency_key)`: com o `tenant_id` fixo, o prefixo é um
 * varrimento de intervalo e não da tabela.
 *
 * **Conta o que saiu e o que está na fila**, ao contrário do medidor do
 * KAM-021: ali a pergunta é «quantas pessoas contactámos» e uma mensagem em
 * `queued` não contactou ninguém; aqui a pergunta é «quantas vezes já tentámos
 * avisar», e uma tentativa na fila é uma tentativa — contá-la de menos fazia o
 * gate avisar uma terceira vez.
 */
export const SQL_AVISOS_ENVIADOS = `
  SELECT count(*)::bigint AS avisos
    FROM platform.outbound_messages
   WHERE tenant_id = $1
     AND conversation_id = $2
     AND idempotency_key LIKE $3
`;

/**
 * O nome da loja, para o marcador do texto do aviso.
 *
 * Parâmetros: `$1` o *tenant*.
 *
 * É o `tenants.nome`, que o dicionário §3.2 declara como «nome do negócio, não
 * de pessoa singular» — e o inventário de `db/tests/test_inventario.py` tem essa
 * resposta escrita na coluna. **Não é dado pessoal**, e é por isso que pode
 * entrar num texto que se envia e num resumo que se guarda.
 */
export const SQL_NOME_DA_LOJA = `
  SELECT nome
    FROM platform.tenants
   WHERE id = $1
`;
