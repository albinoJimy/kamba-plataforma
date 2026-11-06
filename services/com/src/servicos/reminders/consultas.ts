/**
 * O SQL dos lembretes (KAM-048).
 *
 * Em constantes e num módulo só, pela razão que o `../consultas.ts` do KAM-047,
 * o `outbound/consultas.ts` do KAM-015 e o `consentimento/consultas.ts` do
 * KAM-022 já escreveram: a *suite* do *gate* 8 corre **estas** cadeias e não
 * cópias delas, e foi assim que o KAM-009 descobriu um `coalesce` em falta que
 * uma cópia no teste escondia.
 *
 * **São duas, e as outras quatro são de outros módulos.** O que este ticket
 * acrescenta de SQL é o mínimo: o destino de um lembrete e a contagem por
 * *tenant*. A marcação lê-se com o `SQL_MARCACAO` do KAM-047, o serviço com o
 * `SQL_SERVICO`, o consentimento com o `SQL_ESTADO` e o `SQL_TEXTO_VIGENTE` do
 * KAM-022, e a janela e o *template* com o `SQL_JANELA` e o `SQL_TEMPLATE` do
 * KAM-015 — por dentro do `Saida`, que é quem tem a decisão. Reescrever
 * qualquer uma delas aqui era a segunda fonte para o mesmo facto.
 *
 * Tudo parametrizado e com o `tenant_id` no predicado **além** da RLS, pela
 * razão do `SQL_JANELA` do KAM-015: a política já o garante para `kamba_app`,
 * mas um processo de retaguarda pode correr com outro papel, e repeti-lo é o que
 * torna a consulta correcta mesmo corrida sem contexto — devolve zero linhas em
 * vez das de outro.
 */

/**
 * A conversa e o canal por onde o lembrete sai, com a janela.
 *
 * Parâmetros: `$1` o *tenant*, `$2` o contacto.
 *
 * ## Porque é que isto é uma consulta e não um parâmetro
 *
 * Tudo o que o CHR chama recebe um `ChannelContext` já resolvido, porque há uma
 * mensagem de entrada que o resolveu. **Um lembrete não tem isso**: dispara por
 * evento, horas depois da última mensagem, e o `booking.reminder_due` traz
 * `(booking_id, inicio_at)` e mais nada — nem contacto, nem conversa, nem
 * canal. O contacto vem da marcação; a conversa e o canal vêm daqui.
 *
 * ## O `LIMIT 1` é uma leitura, e a limitação dela fica escrita
 *
 * A `conversations` é por `(tenant, contacto, canal)` — é a divergência que a
 * emenda 1.20 registou contra o `docs/tecnica/01` §6.2, e **não se reabre**.
 * Logo um contacto com dois canais do mesmo *tenant* tem duas conversas, e esta
 * consulta escolhe **uma**: a que recebeu mensagem mais recentemente.
 *
 * A leitura: a janela da Meta é por par (número do negócio, número do cliente)
 * (`E1` §4, CONFIRMADO), e a conversa que falou por último é a que tem janela
 * para gastar — nas outras ela está fechada e o lembrete sairia por *template*
 * pago sem necessidade. No Piloto é um canal por *tenant* e a escolha não se
 * exerce; fica escrita porque no dia em que um *tenant* tiver dois, o lembrete
 * vai para a conversa certa por desenho e não por sorte.
 *
 * O `NULLS LAST` não é enfeite: uma conversa que nunca recebeu nada tem
 * `last_inbound_at` nulo, e em PostgreSQL um `NULL` ordena **primeiro** num
 * `DESC` — sem ele, uma conversa que nunca abriu janela ganhava a uma que falou
 * ontem, e o lembrete saía sempre por *template*.
 *
 * O `estado` do canal **não** se filtra aqui, e isso é deliberado: quem decide
 * se um canal `restrito` ou `suspenso` envia é a matriz do KAM-009, por dentro
 * do `Saida` (`STATE_REFUSED`). Filtrar aqui dava `SEM_CONVERSA` para um canal
 * suspenso — o motivo errado, e o que o painel precisa de ver é o estado.
 */
export const SQL_DESTINO = `
  SELECT c.id            AS conversation_id,
         c.channel_id    AS channel_id,
         tc.phone_number_id AS phone_number_id,
         c.window_expires_at AS window_expires_at
    FROM platform.conversations c
    JOIN platform.tenant_channels tc ON tc.id = c.channel_id
   WHERE c.tenant_id = $1 AND c.contact_id = $2
   ORDER BY c.last_inbound_at DESC NULLS LAST
   LIMIT 1
`;

/**
 * Os lembretes de um *tenant* num período: contagem por canal e custo
 * (critério 8).
 *
 * Parâmetros: `$1` o *tenant*, `$2` o início do período, `$3` o fim.
 *
 * ## É uma consulta e **não** uma etiqueta de métrica, e a razão é do §3.14
 *
 * O critério 8 pede «métricas por *tenant*: lembretes enviados, por canal
 * (livre/template), custo e falhas de entrega». O «por *tenant*» não vai numa
 * etiqueta, e isto não é uma escolha deste ticket — é o que o
 * `outbound/metricas.ts` do KAM-015 já decidiu e escreveu, com três razões:
 * as bibliotecas de métricas desta casa recusam por gramática uma etiqueta que
 * não case `^[a-z][a-z0-9_]{1,62}$` e um `tenant_id` é um UUID com hífenes
 * (a chamada **levanta**); o `OBS-I` do `docs/seguranca/ameacas_stride.md`
 * di-lo re-identificação; e o `docs/tecnica/01` §16 aponta o `pricing` dos
 * *status* como o mecanismo. O por-*tenant* sai por consulta, como o
 * `SQL_CUSTO_DO_TENANT` de lá.
 *
 * ## O que distingue um lembrete das outras linhas da tabela é o prefixo da chave
 *
 * `idempotency_key LIKE $4` com o prefixo `%:reminder:%`. É o mesmo mecanismo
 * que o `SQL_AVISOS_ENVIADOS` do KAM-022 usa para contar avisos sem coluna
 * nova, e pela mesma razão: a chave que impede o lembrete de sair duas vezes é
 * a que diz quais linhas são lembretes. Uma coluna `origem` em
 * `outbound_messages` era DDL para uma informação que a chave já carrega — e
 * este ticket não escreve revisões.
 *
 * O prefixo entra como **parâmetro** e não interpolado. Ao contrário do caso do
 * KAM-022, este `LIKE` **não** se resolve pelo índice
 * `outbound_messages_idempotency_uq`: o padrão começa por `%` porque a chave
 * começa pelo `booking_id`. Com o `tenant_id` fixo pelo predicado, é um
 * varrimento das linhas desse *tenant* no período e não da tabela — e a
 * pergunta é de painel, não de caminho de envio. Fica dito para que ninguém o
 * leia como «usa o índice»: *proposta* de calibração se o volume a tornar
 * lenta, e a alternativa é a coluna que hoje se recusa.
 *
 * **Conta o que saiu e o que está na fila**, como o KAM-022 e ao contrário do
 * medidor do KAM-021: a pergunta de um painel de lembretes é «quantos
 * lembretes tentámos», e um `queued` é uma tentativa. O custo, esse, só conta o
 * que a Meta facturou — é o `pricing` dos *status*, que só existe depois de ela
 * responder.
 */
export const SQL_LEMBRETES_DO_TENANT = `
  SELECT kind,
         count(*)::bigint AS tentados,
         count(*) FILTER (WHERE state = 'failed')::bigint AS falhados,
         COALESCE(SUM(CASE
             WHEN pricing IS NULL THEN 0
             WHEN NOT (pricing->>'billable')::boolean THEN 0
             WHEN pricing->>'category' = 'marketing' THEN 22500
             ELSE 4000
         END), 0)::bigint AS micro_usd
    FROM platform.outbound_messages
   WHERE tenant_id = $1
     AND created_at >= $2
     AND created_at < $3
     AND idempotency_key LIKE $4
   GROUP BY kind
   ORDER BY kind
`;

/**
 * O padrão que isola as linhas de lembrete. Ver o `SQL_LEMBRETES_DO_TENANT`.
 *
 * Deriva da `ETIQUETA_DA_ORDEM`? **Não**, e de propósito: o que identifica um
 * lembrete é o segmento `:reminder:` da chave do critério 2, e esse não muda se
 * a antecedência for calibrada de `T-24h` para outro valor. Um padrão que
 * levasse a etiqueta deixava de contar os lembretes antigos no dia da
 * calibração, e o painel mostrava uma queda que não aconteceu.
 */
export const PADRAO_DE_LEMBRETE = "%:reminder:%";
