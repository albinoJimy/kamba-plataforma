/**
 * O SQL da qualidade do canal (KAM-021).
 *
 * Em constantes e num módulo só, pela razão que o `outbound/consultas.ts` do
 * KAM-015 e o `chr/consultas.ts` do KAM-014 escreveram: a *suite* do *gate* 8
 * corre **estas** cadeias e não cópias delas, e foi assim que o KAM-009
 * descobriu um `coalesce` em falta que uma cópia no teste escondia.
 *
 * ## Tudo parametrizado, e o `tenant_id` no predicado além da RLS
 *
 * O módulo corre como `kamba_app`, sujeito à RLS, mas um processo de retaguarda
 * pode chamá-lo com outro papel; uma interpolação aqui lia os canais de todos os
 * *tenants* no dia em que alguém a chamasse com o papel errado. O `tenant_id`
 * está no predicado **além** da política pela razão do `SQL_JANELA` do KAM-015:
 * ela já o garante, e repeti-lo é o que torna a consulta correcta mesmo corrida
 * sem contexto — devolve zero linhas em vez do canal de outro.
 */

/**
 * O canal pelo seu `phone_number_id`, com o que a qualidade precisa de saber.
 *
 * Lê-se **antes** de escrever, e não é uma leitura optimista: o `estado` e o
 * `quality_rating` anteriores são o que decide se há transição, e o
 * `motivo_restricao` é o que decide se se pode repor. As escritas que dependem
 * disto levam o predicado consigo — ver as notas do `SQL_RESTRINGIR` e do
 * `SQL_REPOR` —, pelo que esta leitura serve para **decidir** e não para
 * proteger.
 */
export const SQL_CANAL = `
  SELECT id::text        AS channel_id,
         phone_number_id AS phone_number_id,
         estado          AS estado,
         quality_rating  AS quality_rating,
         messaging_limit AS messaging_limit,
         motivo_restricao AS motivo_restricao
    FROM platform.tenant_channels
   WHERE tenant_id = $1 AND phone_number_id = $2
`;

/**
 * Registra uma transição, e **não faz nada** se a chave já passou.
 *
 * Parâmetros: `$1` o *tenant*, `$2` o canal, `$3` o evento, `$4` o valor
 * anterior (`NULL` na primeira linha), `$5` o valor novo **tal e qual**, `$6` a
 * chave, `$7` o instante que a Meta diz (`NULL` para `now()`).
 *
 * ## A idempotência do critério 6 é da base, e o `RETURNING` vazio é o sinal
 *
 * `ON CONFLICT (tenant_id, event_key) DO NOTHING RETURNING id`: o
 * `RETURNING` vazio significa «este evento já foi tratado». Não há `SELECT`
 * antes do `INSERT` — entre o `SELECT` e o `INSERT` cabe outro processo, e o
 * critério pede **uma** transição, não «quase sempre uma». Com `ON CONFLICT`,
 * quem perde a corrida sabe que perdeu.
 *
 * É a mesma forma do `SQL_ENFILEIRAR` do KAM-015, e a razão de ela estar aqui
 * **outra vez** é que o registo de entrada (`inbound_events`, da `0008`) dedupe
 * o **corpo** e não o encaminhamento: o `registo.ts` do KAM-013 diz por extenso
 * que registar e encaminhar não são atómicos e que «todo o tratador de destino
 * tem de ser idempotente».
 *
 * **O `valor_novo` é o bruto da Meta.** Guardar o canónico aqui perdia a única
 * informação que o critério 1 pede para um valor desconhecido: qual era.
 */
export const SQL_REGISTAR_TRANSICAO = `
  INSERT INTO platform.channel_quality_log
         (tenant_id, channel_id, evento, valor_anterior, valor_novo,
          event_key, ocorrido_em)
  VALUES ($1, $2, $3, $4, $5, $6, coalesce($7, now()))
      ON CONFLICT (tenant_id, event_key) DO NOTHING
   RETURNING id
`;

/**
 * Escreve a qualidade canónica no canal.
 *
 * Parâmetros: `$1` o *tenant*, `$2` o canal, `$3` a qualidade canónica.
 *
 * Instrução própria e não junta à do estado, e a razão é que as duas respondem
 * a perguntas diferentes: esta corre **sempre** que a Meta manda um valor que
 * se reconhece, e a do estado corre **só** quando há transição. Juntá-las
 * obrigava a escrever o estado igual a ele mesmo no caso comum, que é o caso em
 * que o canal está `ativo` e continua `ativo`.
 */
export const SQL_ESCREVER_QUALIDADE = `
  UPDATE platform.tenant_channels
     SET quality_rating = $3
   WHERE tenant_id = $1 AND id = $2
   RETURNING quality_rating
`;

/**
 * Passa o canal a `restrito` por qualidade, e diz se foi esta chamada a fazê-lo
 * (critério 2).
 *
 * Parâmetros: `$1` o *tenant*, `$2` o canal.
 *
 * ## Duas colunas numa instrução, e isso é atomicidade e não economia
 *
 * O `estado` e o `motivo_restricao` escrevem-se juntos. Separá-los deixava uma
 * janela em que o canal está `restrito` e não diz porquê — e é precisamente
 * nessa janela que o KAM-115 iria avisar o dono sem saber o que lhe dizer, e
 * que o painel mostraria uma loja cortada sem razão. É o mesmo argumento do
 * `SQL_MARCAR_RESTRICAO` do KAM-023 para a marca e o código.
 *
 * ## O `WHERE estado <> 'restrito'` é a transição, e o `RETURNING` vazio é o
 * «já estava»
 *
 * O critério pede «1 transição» e um `red` repetido não é uma transição nova.
 * Com o predicado no próprio `UPDATE`, quem o corre duas vezes em paralelo vê
 * **um** `RETURNING` com linha e o outro vazio — é a base que serializa, como no
 * `SQL_AVANCAR_ESTADO` do KAM-015. Sem ele, os dois leriam `ativo`, os dois
 * escreveriam, e os dois emitiriam `channel.updated`.
 *
 * **O `motivo_restricao` usa `COALESCE`** pela razão do KAM-023: se o canal já
 * estivesse marcado por falta de pagamento — o que não acontece com
 * `estado <> 'restrito'`, mas a coluna é independente do estado —, a primeira
 * marca é a que fica.
 */
export const SQL_RESTRINGIR = `
  UPDATE platform.tenant_channels
     SET estado = 'restrito',
         motivo_restricao = COALESCE(motivo_restricao, 'quality')
   WHERE tenant_id = $1
     AND id = $2
     AND estado <> 'restrito'
   RETURNING id
`;

/**
 * Devolve o canal a `ativo`, e **só** se a restrição for de qualidade
 * (critério 2).
 *
 * Parâmetros: `$1` o *tenant*, `$2` o canal.
 *
 * ## O `motivo_restricao = 'quality'` no predicado é o centro desta consulta
 *
 * Um canal restrito por **falta de método de pagamento** (KAM-023) continua a
 * ter qualidade: a Meta deixa de entregar, mas o `quality_rating` pode muito
 * bem voltar a `green`. Repor o estado nesse caso era desfazer a decisão de
 * outro ticket a partir de um sinal que não lhe diz respeito — e o resultado
 * prático era uma loja a voltar a `ativo` com a Meta ainda a recusar as
 * mensagens dela.
 *
 * É a mesma regra que a `levantarRestricao` do KAM-023 escreveu pelo outro
 * lado, e as duas juntas dizem a propriedade inteira: **cada ticket levanta
 * apenas o motivo que põe.**
 *
 * O `RETURNING` vazio significa «não havia uma restrição de qualidade para
 * levantar», e quem lê trata-o como tal: não emite evento nenhum.
 */
export const SQL_REPOR = `
  UPDATE platform.tenant_channels
     SET estado = 'ativo',
         motivo_restricao = NULL
   WHERE tenant_id = $1
     AND id = $2
     AND estado = 'restrito'
     AND motivo_restricao = 'quality'
   RETURNING id
`;

/**
 * Persiste o escalão de mensagens e o tecto do portfólio (critério 5).
 *
 * Parâmetros: `$1` o *tenant*, `$2` o canal, `$3` o escalão (`NULL` para não
 * mexer), `$4` o tecto de números (`NULL` para não mexer).
 *
 * Os dois `COALESCE` são o que torna a consulta útil para um
 * `business_capability_update` que traga só um dos dois campos — o que acontece,
 * porque a Meta manda o que mudou. Sem eles, um corpo sem
 * `max_phone_numbers_per_business` apagava o tecto que já se sabia.
 *
 * **Usa o `whatsapp_business_manager_messaging_limit` e não o
 * `messaging_limit_tier`**, que está **deprecado** (CONFIRMADO, `E1` §5). Quem
 * escolhe o campo é quem lê o corpo; o que esta consulta garante é que a coluna
 * guarda um só valor e que ele vem de um sítio.
 */
export const SQL_ESCREVER_LIMITES = `
  UPDATE platform.tenant_channels
     SET messaging_limit = COALESCE($3, messaging_limit),
         max_phone_numbers_per_business =
             COALESCE($4::integer, max_phone_numbers_per_business)
   WHERE tenant_id = $1 AND id = $2
   RETURNING messaging_limit, max_phone_numbers_per_business
`;

/**
 * Pausa localmente o envio de um template (critério 5).
 *
 * Parâmetros: `$1` o *tenant*, `$2` o nome, `$3` o idioma, `$4` a qualidade
 * nova em canónico (`NULL` para não mexer).
 *
 * «`message_template_quality_update` pausa **localmente** o envio do template
 * afectado» — e o «localmente» é a palavra que importa: a Meta não pausou nada,
 * nós é que deixamos de enviar. O `status` passa a `paused`, que é um valor que
 * o `message_templates_status_ck` da `0010` já aceita, e o
 * `decidir` do KAM-015 recusa um template cujo `status` não seja `approved`.
 *
 * **Pelo idioma exacto e não por prefixo**, pela razão do `SQL_TEMPLATE` do
 * KAM-015: `pt_PT` e `pt_BR` são templates diferentes com corpos diferentes, e
 * um `LIKE 'pt%'` pausava um pelo outro.
 *
 * O `updated_at = now()` sempre, mesmo quando o valor não muda: é o que diz «a
 * Meta confirmou isto agora», e um template cujo `updated_at` pare é um
 * template de que deixámos de ouvir falar — a nota é do
 * `SQL_ESTADO_DO_TEMPLATE` do KAM-015.
 */
export const SQL_PAUSAR_TEMPLATE = `
  UPDATE platform.message_templates
     SET status = 'paused',
         quality = COALESCE($4, quality),
         updated_at = now()
   WHERE tenant_id = $1 AND name = $2 AND lang = $3
   RETURNING name, status, quality
`;

/**
 * Marca os templates de um *tenant* para revisão (critério 4).
 *
 * Parâmetros: `$1` o *tenant*, `$2` a qualidade canónica a escrever.
 *
 * «YELLOW […] marca os templates para revisão.» Marca e **não** pausa: um
 * `yellow` no número não é um veredicto sobre nenhum template em particular, e
 * pausar todos por causa dele cortava a loja por um aviso. O que se escreve é a
 * `quality`, que é o campo que quem revê vai ler.
 *
 * **Só os aprovados**, e isso é escopo: um template `rejected` ou `disabled` não
 * tem revisão que fazer, e um `pending` ainda está com a Meta. O
 * `RETURNING count` sai por linha, e quem chama conta.
 *
 * **Marca os templates do *tenant* inteiro e não só os do canal, e isso é o
 * esquema e não uma escolha.** A `message_templates` tem chave primária
 * `(tenant_id, name, lang)` e **não tem coluna de canal** (revisão `0010`): um
 * template é da conta e não do número. Um *tenant* com dois números vê os
 * templates marcados por um `yellow` no outro, e a alternativa — marcar só
 * alguns — exigia saber quais foram enviados por qual número, que é informação
 * de `outbound_messages` e não da tabela dos templates. Marcar é barato e
 * reversível (quem revê lê a `quality`); pausar seria o que não se podia fazer
 * assim, e é por isso que o `yellow` **marca** e não pausa.
 */
export const SQL_MARCAR_TEMPLATES = `
  UPDATE platform.message_templates
     SET quality = $2,
         updated_at = now()
   WHERE tenant_id = $1
     AND status = 'approved'
   RETURNING name
`;

/**
 * Utilizadores únicos contactados **por template** nas últimas 24 h
 * (critério 7).
 *
 * Parâmetros: `$1` o *tenant*, `$2` o `phone_number_id`, `$3` o instante
 * (`NULL` para `now()`).
 *
 * ## O que conta, e o que não conta
 *
 * `count(DISTINCT contact_id)` sobre `outbound_messages`, com três filtros, e
 * cada um é uma linha do critério:
 *
 * * **`kind <> 'service'`** — «resposta dentro da janela não consome». O limite
 *   da Meta é sobre **iniciar** conversas fora da janela (CONFIRMADO, `E1` §5),
 *   e uma `service` é, por definição, a mensagem livre dentro da janela: ela
 *   responde, não inicia;
 * * **24 h móveis** — e não «hoje». O `E1` §5 diz «utilizadores únicos em 24 h
 *   **móveis**», pelo que a janela conta para trás a partir do instante e não a
 *   partir da meia-noite de fuso nenhum. **É por isso que esta consulta não
 *   chama o `platform.ten_periodo`**, ao contrário do contador do KAM-023: o
 *   mês do *free tier* reinicia à meia-noite de um fuso; este não reinicia, vai
 *   andando;
 * * **só o que saiu** — `state <> 'queued'`. Uma mensagem que nunca foi
 *   entregue à Meta não contactou ninguém, e contá-la fazia o rácio subir por
 *   envios que a nossa própria fila ainda tinha em mão.
 *
 * A junção por `tenant_channels` existe porque `outbound_messages` guarda
 * `channel_id` e não o número — o mesmo desencontro que o KAM-023 registou na
 * dívida 68 —, e leva `tenant_id` nos **dois** lados, como todas as FK desde a
 * `0003`.
 */
export const SQL_UNICOS_FORA_DA_JANELA = `
  SELECT count(DISTINCT m.contact_id)::bigint AS unicos
    FROM platform.outbound_messages AS m
    JOIN platform.tenant_channels AS c
      ON c.tenant_id = m.tenant_id AND c.id = m.channel_id
   WHERE m.tenant_id = $1
     AND c.phone_number_id = $2
     AND m.kind <> 'service'
     AND m.state <> 'queued'
     AND m.created_at >= coalesce($3, now()) - interval '24 hours'
`;
