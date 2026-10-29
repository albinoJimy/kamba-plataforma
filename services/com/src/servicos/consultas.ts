/**
 * O SQL do módulo `servicos`, por extenso (KAM-047).
 *
 * Num ficheiro só, pela razão do `ten/consultas.ts` e do `modos/consultas.ts`:
 * o texto que a biblioteca envia é o que o *gate* 8 exercita contra um
 * PostgreSQL verdadeiro, e um SQL escrito dentro da função que o usa nunca é
 * confrontado como texto. Quando a suite de base de dados importa estas
 * constantes, o que ela prova é **a consulta de produção** e não uma cópia dela
 * — a lição que a revisão adversarial do KAM-009 deixou escrita (`SQL_PERIODO`
 * tinha um defeito real que nenhum teste tocava).
 *
 * Todas as consultas correm **dentro** de uma transacção com `app.tenant_id`
 * definido. Nenhuma leva `tenant_id` no `WHERE`, e isso é deliberado: a RLS é
 * que o põe lá. Um `WHERE tenant_id = $1` escrito à mão ao lado da política
 * criava uma segunda fonte para a mesma regra, e no dia em que as duas
 * discordassem a que mandava era a mais fraca. As escritas levam `tenant_id` na
 * lista de colunas porque a coluna é `NOT NULL` e o `WITH CHECK` da política o
 * confronta com o contexto — é a barreira a ser exercida, não a ser contornada.
 */

/** Os serviços activos do tenant. */
export const SQL_LISTAR_SERVICOS = `
  SELECT service_id, nome, duracao_min, preco_tipo, preco_minor, currency
    FROM servicos.services
   WHERE ativo
   ORDER BY nome
`;

/** Um serviço pelo identificador, activo ou não. */
export const SQL_SERVICO = `
  SELECT service_id, nome, duracao_min, preco_tipo, preco_minor, currency, ativo
    FROM servicos.services
   WHERE service_id = $1::uuid
`;

/**
 * As regras de disponibilidade dos recursos activos, para o horizonte pedido.
 *
 * Devolve uma linha por `(recurso, dia da grelha)` **já resolvida em
 * instantes**: a junção do `generate_series` de dias com as regras faz-se em
 * SQL porque é aqui que o fuso se aplica, e aplicá-lo em JavaScript obrigava a
 * uma biblioteca de fusos no serviço para repetir o que o `tzdata` do servidor
 * já sabe.
 *
 * `(d + inicio) AT TIME ZONE fuso` lê-se da direita para a esquerda: o par
 * `(dia, hora local)` é interpretado **no fuso da regra** e sai como
 * `timestamptz`. É a forma que faz o horário de verão de um fuso que o tenha
 * cair no sítio certo sem ninguém somar horas à mão.
 *
 * O `dow` do PostgreSQL devolve `0` para domingo, que é a convenção que a
 * coluna `dia_semana` segue (ver a revisão `0025`).
 *
 * **O `generate_series` corre sobre `date` e não sobre `timestamptz`**, e isso
 * foi um defeito que a revisão adversarial apanhou: com os instantes, uma
 * janela que atravesse a meia-noite sem chegar a 24 h perde o segundo dia —
 * `generate_series('02T20:00', '03T12:00', interval '1 day')` devolve **um**
 * valor, porque o passo seguinte (03T20:00) cai depois do fim. Um cliente que
 * pedisse «de hoje à noite até amanhã ao almoço» recebia lista vazia com o
 * recurso aberto das 9 às 17. Truncar para `date` **antes** da série, e não
 * depois, é o que faz os dois dias entrarem.
 */
export const SQL_GRELHA = `
  WITH dias AS (
    SELECT d::date AS dia
      FROM generate_series($1::timestamptz::date, $2::timestamptz::date,
                           interval '1 day') AS d
  )
  SELECT r.resource_id,
         ((dias.dia + a.inicio) AT TIME ZONE a.fuso) AS abre_at,
         ((dias.dia + a.fim) AT TIME ZONE a.fuso)    AS fecha_at
    FROM dias
    JOIN servicos.availability_rules AS a
      ON a.dia_semana = EXTRACT(dow FROM dias.dia)::smallint
    JOIN servicos.resources AS r
      ON r.resource_id = a.resource_id
   WHERE r.ativo
   ORDER BY abre_at, r.resource_id
`;

/**
 * As marcações que ocupam o intervalo, por recurso.
 *
 * Só os dois estados activos, que são os mesmos do predicado da restrição de
 * exclusão: uma `cancelada` ou `expirada` não ocupa nada, e lê-la aqui fazia a
 * disponibilidade esconder horas que estavam livres.
 *
 * O teste da sobreposição é `fim_at > $1 AND inicio_at < $2` — a mesma
 * semântica `[)` da restrição de exclusão, pelo que uma marcação que **acaba**
 * quando a janela começa não conta como ocupada.
 *
 * **Os parâmetros aparecem por ordem**, e isso não é estética: a suite de base
 * de dados lê estas constantes do próprio ficheiro e converte `$n` em `%s`
 * posicional, que é posicional *pela ordem de aparição*. A primeira versão
 * escrevia `inicio_at < $2 AND fim_at > $1`, a conversão trocou os dois
 * argumentos, e o teste de isolamento acusou a RLS de esconder a marcação do
 * próprio tenant. O conversor passou a recusar uma consulta fora de ordem.
 */
export const SQL_OCUPADO = `
  SELECT resource_id, inicio_at, fim_at
    FROM servicos.bookings
   WHERE estado IN ('hold', 'confirmada')
     AND fim_at    > $1::timestamptz
     AND inicio_at < $2::timestamptz
   ORDER BY resource_id, inicio_at
`;

/**
 * O *slot* ainda é oferecível? Corre antes de cada escrita na agenda.
 *
 * **A assinatura do `slot_id` prova que o backend o ofereceu; não prova que
 * ainda o ofereceria.** É a distinção que a revisão adversarial trouxe, e o
 * cenário é concreto: na segunda-feira o cliente recebe a lista com o *slot* de
 * quinta às 15h; na terça a PME apaga a regra de quinta, ou desactiva o
 * profissional, ou desactiva o serviço; na quarta o cliente carrega no botão. A
 * assinatura continua boa, a restrição de exclusão não se opõe (o intervalo
 * está livre, e está livre precisamente porque a PME o fechou), e sem esta
 * consulta a marcação **entra** — num recurso desactivado e fora do horário.
 *
 * Quatro coisas numa consulta, e cada uma fecha um caso:
 *
 * - o **serviço** existe e está `ativo`;
 * - o **recurso** existe e está `ativo`;
 * - a duração do intervalo é **exactamente** a `duracao_min` do serviço — sem
 *   isto, um *token* de um serviço de 30 min marcava 30 min de um serviço que
 *   entretanto passou a 60;
 * - o intervalo cabe dentro de uma **regra de disponibilidade** do recurso, no
 *   dia e no fuso dela.
 *
 * Isto não substitui a restrição de exclusão nem o `getAvailability`: é a
 * terceira barreira, e a única que olha para a **agenda declarada** em vez de
 * para as marcações. Sem ela, os Detalhes Técnicos do bloco — «disponibilidade
 * = `availability_rules` do recurso menos marcações activas» — valiam só no
 * instante em que a lista foi gerada.
 *
 * **Os quatro argumentos entram num `SELECT` à parte e usam-se por nome**, e
 * isso não é estilo: a suite de base de dados converte `$n` em `%s` posicional,
 * e um `$n` repetido não tem equivalente posicional nenhum. A primeira versão
 * escrevia `$3` e `$4` quatro vezes cada, e o conversor **recusou-a** com a
 * razão por extenso — o que é o conversor a fazer o trabalho dele. Ligados uma
 * vez no `pedido`, cada parâmetro aparece uma só vez e por ordem.
 */
export const SQL_SLOT_OFERECIVEL = `
  SELECT EXISTS (
    SELECT 1
      FROM (SELECT $1::uuid        AS service_id,
                   $2::uuid        AS resource_id,
                   $3::timestamptz AS inicio_at,
                   $4::timestamptz AS fim_at) AS pedido
      JOIN servicos.services  AS s ON s.service_id  = pedido.service_id  AND s.ativo
      JOIN servicos.resources AS r ON r.resource_id = pedido.resource_id AND r.ativo
      JOIN servicos.availability_rules AS a ON a.resource_id = r.resource_id
     WHERE pedido.inicio_at < pedido.fim_at
       AND (pedido.fim_at - pedido.inicio_at)
           = make_interval(mins => s.duracao_min)
       AND a.dia_semana
           = EXTRACT(dow FROM (pedido.inicio_at AT TIME ZONE a.fuso))::smallint
       AND (pedido.inicio_at AT TIME ZONE a.fuso)::time >= a.inicio
       AND (pedido.fim_at    AT TIME ZONE a.fuso)::time <= a.fim
  ) AS oferecivel
`;

/**
 * Serializa as escritas na agenda de **um** recurso, antes do `INSERT`.
 *
 * `pg_advisory_xact_lock` por `(tenant_id, resource_id)`, com o prefixo
 * `servicos:` — a mesma forma do `SQL_TRANCAR_CONVERSA` do KAM-018, e o prefixo
 * existe para **não** cair no espaço de chaves daquele: ele usa
 * `hashtextextended(tenant || ':' || contact, 0)`, e o repositório já mediu que
 * a chave do KAM-025 colide com a dele. Um `resource_id` e um `contact_id` são
 * os dois UUID; sem o prefixo, marcar uma hora podia bloquear uma transição de
 * modo.
 *
 * ## Isto **não** é o que garante o critério 1, e foi medido
 *
 * A pergunta certa é se este *lock* substitui a restrição de exclusão. Não
 * substitui, e a diferença é demonstrável: um *lock* **serializa** tentativas,
 * não recusa nenhuma. Com a restrição removida e o *lock* no lugar, as
 * tentativas passam a entrar **uma a uma e todas** — é exactamente o que o
 * `test_sem_a_restricao_as_mil_dariam_mais_do_que_uma` afirma, e é o passo de
 * canário que prova qual das duas é a barreira.
 *
 * ## Porque é que ele existe: 486 *deadlocks* medidos
 *
 * Sem ele, as mil tentativas do critério 1 **não terminam em tempo útil**, e a
 * razão não é carga: é que a verificação de uma restrição de exclusão espera
 * pela transacção com que conflitua, e com N inserções concorrentes da mesma
 * chave cada uma pode encontrar um conflito **diferente** — o que fecha um ciclo
 * de espera. Medido a 2026-10-28 contra o PostgreSQL 18.6 da imagem fixada: 32
 * ligações, **486 `deadlock detected`** em `pg_stat_database`, um por segundo
 * (o `deadlock_timeout` por omissão), com a prova a não progredir.
 *
 * E o que isso fazia ao critério era pior do que a lentidão: as tentativas
 * perdedoras voltavam com `40P01` e não com `23P01`, pelo que «as restantes
 * `SLOT_TAKEN`» era falso — o cliente recebia um erro de base de dados em vez
 * de «esse horário acabou de ficar ocupado». Com o *lock*, as perdedoras voltam
 * todas com `23P01`.
 *
 * **Por `(tenant, recurso)` e não pelo intervalo**, e isso é deliberado: dois
 * intervalos que se sobrepõem sem serem iguais — 9h–10h e 9h30–10h30 — dão
 * chaves diferentes e voltavam a poder entrar em ciclo. Um recurso é um
 * profissional ou uma sala, e serializar as marcações de um deles custa nada:
 * a frequência é de minutos, não de milissegundos.
 *
 * **E não se mapeia `40P01` para `SLOT_TAKEN`.** Seria a reparação tentadora e
 * é uma mentira: um *deadlock* diz que a transacção foi desfeita, não que
 * alguém ficou com o horário. Fica como excepção — que é a classificação
 * honesta de uma falha de infra — e o que a torna rara é este *lock*.
 */
export const SQL_TRANCAR_RECURSO = `
  SELECT pg_advisory_xact_lock(
    hashtextextended('servicos:' || $1::text || ':' || $2::text, 0))
`;

/**
 * Cria o hold. **Um `INSERT`, e nenhuma leitura antes dele.**
 *
 * Não há `SELECT` a perguntar se o intervalo está livre: entre o `SELECT` e o
 * `INSERT` cabe outra transacção, e o critério 1 pede **uma** marcação e não
 * «quase sempre uma». Quem recusa é a restrição de exclusão
 * `bookings_sem_sobreposicao`, com `SQLSTATE 23P01`, e quem chama traduz isso
 * em `SLOT_TAKEN`. É a mesma forma do `SQL_REGISTAR_TRANSICAO` da `0014` e do
 * `SQL_ENFILEIRAR` da `0010`.
 *
 * O `SQL_TRANCAR_RECURSO` corre antes, e é outra coisa: não decide nada, só põe
 * as tentativas em fila para que a recusa seja `23P01` e não um *deadlock*. Ver
 * a nota dele.
 *
 * O `hold_id` e o `booking_id` são gerados pela base (omissões da coluna): dois
 * identificadores gerados no serviço eram dois sítios onde uma repetição podia
 * nascer.
 */
export const SQL_CRIAR_HOLD = `
  INSERT INTO servicos.bookings
         (tenant_id, contact_id, service_id, resource_id, slot_id,
          inicio_at, fim_at, estado, hold_expires_at)
  VALUES ($1::uuid, $2::uuid, $3::uuid, $4::uuid, $5,
          $6::timestamptz, $7::timestamptz, 'hold', $8::timestamptz)
  RETURNING booking_id, hold_id, contact_id, service_id, resource_id, slot_id,
            inicio_at, fim_at, estado, hold_expires_at, version
`;

/**
 * Cria a marcação remarcada, **no estado da original**.
 *
 * Gémea do `SQL_CRIAR_HOLD`, e existe por um defeito que a revisão adversarial
 * encontrou: a remarcação usava o `SQL_CRIAR_HOLD`, que escreve `'hold'`
 * literal, e por isso **degradava uma marcação confirmada num hold de dez
 * minutos**. Quem remarcasse uma marcação já confirmada e não voltasse a
 * carregar no botão perdia-a em silêncio — o varrimento expirava-a e emitia
 * `booking.cancelled` por uma marcação que o cliente julgava ter.
 *
 * O `$9` é o estado e o `$10` o prazo, e a coerência entre os dois é do
 * `bookings_hold_prazo_ck`: `hold` com prazo, `confirmada` sem. Quem chama
 * passa o par da marcação original.
 */
export const SQL_REMARCAR = `
  INSERT INTO servicos.bookings
         (tenant_id, contact_id, service_id, resource_id, slot_id,
          inicio_at, fim_at, estado, hold_expires_at)
  VALUES ($1::uuid, $2::uuid, $3::uuid, $4::uuid, $5,
          $6::timestamptz, $7::timestamptz, $8, $9::timestamptz)
  RETURNING booking_id, hold_id, contact_id, service_id, resource_id, slot_id,
            inicio_at, fim_at, estado, hold_expires_at, version
`;

/** A marcação activa deste contacto para este slot, se existir. */
export const SQL_MARCACAO_DO_SLOT = `
  SELECT booking_id, hold_id, contact_id, service_id, resource_id, slot_id,
         inicio_at, fim_at, estado, hold_expires_at, version
    FROM servicos.bookings
   WHERE contact_id = $1::uuid AND slot_id = $2
     AND estado IN ('hold', 'confirmada')
`;

/**
 * Confirma o hold. **O `WHERE` é a idempotência, e não um `SELECT` antes.**
 *
 * `estado = 'hold' AND hold_expires_at > now()`: a primeira das cinquenta
 * chamadas concorrentes do critério 4 altera a linha, e as outras quarenta e
 * nove não encontram linha nenhuma para alterar — devolvem zero linhas, e quem
 * chama vai ler o estado actual. O `UPDATE` serializa no bloqueio da linha, que
 * é o que faz disto uma barreira e não uma corrida.
 *
 * O `hold_expires_at > now()` é o `HOLD_EXPIRED` do critério 3 **na base**: um
 * hold vencido não se confirma, mesmo que o varrimento ainda não lhe tenha
 * chegado. Sem ele, o resultado de confirmar um hold vencido dependia de o
 * varrimento ter corrido — e isso é uma corrida com o relógio, não uma regra.
 *
 * **O `contact_id` está no `WHERE`, e isso mudou.** A primeira versão
 * confirmava primeiro e conferia o dono depois, lançando por dentro para que a
 * transacção se desfizesse — e a justificação era a qualidade da mensagem de
 * erro (distinguir `HOLD_EXPIRED` de `NOT_FOUND`). A revisão adversarial
 * mostrou o preço: uma escrita feita **antes** da autorização, que durante a
 * transacção segura o bloqueio da linha de outro contacto e põe uma confirmação
 * legítima à espera. A distinção resolve-se com a leitura que já existe a
 * seguir (`SQL_MARCACAO_POR_HOLD`), sem escrever primeiro. É a mesma forma que
 * o `SQL_CANCELAR` já tinha.
 */
export const SQL_CONFIRMAR_HOLD = `
  UPDATE servicos.bookings
     SET estado = 'confirmada', hold_expires_at = NULL, version = version + 1
   WHERE hold_id = $1::uuid AND contact_id = $2::uuid
     AND estado = 'hold' AND hold_expires_at > now()
  RETURNING booking_id, hold_id, contact_id, service_id, resource_id, slot_id,
            inicio_at, fim_at, estado, hold_expires_at, version
`;

/** A marcação por `hold_id`, em qualquer estado. Para a resposta idempotente. */
export const SQL_MARCACAO_POR_HOLD = `
  SELECT booking_id, hold_id, contact_id, service_id, resource_id, slot_id,
         inicio_at, fim_at, estado, hold_expires_at, version
    FROM servicos.bookings
   WHERE hold_id = $1::uuid
`;

/** A marcação por `booking_id`, em qualquer estado. */
export const SQL_MARCACAO = `
  SELECT booking_id, hold_id, contact_id, service_id, resource_id, slot_id,
         inicio_at, fim_at, estado, hold_expires_at, version
    FROM servicos.bookings
   WHERE booking_id = $1::uuid
`;

/**
 * Cancela. **Liberta o intervalo imediatamente** (critério 5).
 *
 * «Imediatamente» é literal e não uma promessa de latência: a restrição de
 * exclusão é **parcial** sobre `estado IN ('hold','confirmada')`, pelo que a
 * linha sai do índice no mesmo `UPDATE` — e o intervalo está livre antes de a
 * transacção confirmar, para quem estiver nela. Não há `DELETE`, e por isso o
 * histórico fica.
 *
 * O `contact_id = $2` não é redundante com a RLS: a política isola **tenants**,
 * e o que isto impede é um contacto cancelar a marcação de outro **dentro do
 * mesmo tenant** — o X-02 do critério 6.
 */
export const SQL_CANCELAR = `
  UPDATE servicos.bookings
     SET estado = 'cancelada', hold_expires_at = NULL, version = version + 1
   WHERE booking_id = $1::uuid AND contact_id = $2::uuid
     AND estado IN ('hold', 'confirmada')
  RETURNING booking_id, hold_id, contact_id, service_id, resource_id, slot_id,
            inicio_at, fim_at, estado, hold_expires_at, version
`;

/** O varrimento do critério 3, como função da revisão `0025`. */
export const SQL_EXPIRAR_HOLDS = `SELECT servicos.expirar_holds($1::integer) AS libertados`;

/** A emissão de um evento de marcação pelo outbox (`platform.evt_emitir`). */
export const SQL_EMITIR_BOOKING_CREATED = `
  SELECT platform.evt_emitir(
    $1, $2::smallint, $3::uuid, $4, $5, $6::jsonb, $7, $8::text[]
  ) AS event_id
`;

/**
 * Os motivos de um `booking.cancelled`. Domínio **fechado**.
 *
 * O `motivo` do contrato v1 é texto livre, e deixá-lo assim era convidar a que
 * cada chamador escrevesse o seu — e a que o consumidor do KAM-048 tivesse de
 * adivinhar. Dois valores: o varrimento (na revisão `0025`) e o cliente.
 */
export const MOTIVOS_DE_CANCELAMENTO = ["hold_expirado", "cancelado_pelo_cliente"] as const;
export type MotivoDeCancelamento = (typeof MOTIVOS_DE_CANCELAMENTO)[number];

/** `23P01`: violação de restrição de exclusão. É o `SLOT_TAKEN` do critério 1. */
export const SQLSTATE_SOBREPOSICAO = "23P01";

/**
 * `23505`: violação de unicidade.
 *
 * Aqui só pode vir de `bookings_contacto_slot_uq` — o mesmo contacto a pedir o
 * mesmo slot duas vezes em paralelo. Trata-se como `SLOT_TAKEN` e não como erro:
 * do ponto de vista de quem pediu, o slot ficou tomado (por ele próprio), e a
 * leitura seguinte devolve-lhe a marcação que já tem.
 */
export const SQLSTATE_UNICIDADE = "23505";
