/**
 * O SQL do CHR (KAM-014), num ficheiro só.
 *
 * Está separado da lógica pela mesma razão que o `entrada/consultas.ts` está
 * separado do `registo.ts`: a suite de base de dados (`db/tests_chr/`) lê estas
 * constantes **deste ficheiro** e exercita-as contra um PostgreSQL real, pela
 * classe `ConsultaDoTypeScript` de `db/tests/base.py`. Uma cópia do SQL no
 * teste provava que a cópia funciona.
 *
 * **Os marcadores são `$n` e a ordem em que aparecem no texto importa**: o
 * `pg8000` da suite Python não tem `$n`, tem `%s`, e liga-os pela ordem de
 * aparição. A `ConsultaDoTypeScript` reordena, mas só se a numeração for
 * contígua a partir de 1.
 *
 * ## Três papéis, três grupos de consultas
 *
 * `kamba_resolver` responde a pergunta que se faz **antes** de haver contexto
 * (a que tenant pertence este `phone_number_id`) e corre a guarda de arranque
 * do ADR-011. `kamba_app` abre e lê a conversa, **com** contexto de tenant.
 * `kamba_identity` reaponta conversas numa fusão de contactos, dentro da
 * transacção da fusão. Nenhum dos três faz o trabalho de outro, e os
 * privilégios da revisão `0009` são exactamente estes.
 */

/**
 * O canal e o tenant de um `phone_number_id`. Corre como `kamba_resolver`.
 *
 * Sem contexto de tenant, e é isso que o papel existe para permitir: a política
 * `resolver_leitura` (`FOR SELECT TO kamba_resolver USING (true)`) deixa-o ver
 * as linhas de todos os tenants, em dez colunas e mais nada.
 *
 * **Devolve zero ou uma linha**, e isso é a `tenant_channels_phone_number_id_uq`
 * da `0001`: o `phone_number_id` é único em toda a plataforma, sem `tenant_id`
 * na chave. É o que torna a resolução determinística — e é também o que faz o
 * `phone_number_id` de A nunca poder devolver o contexto de B, porque não há
 * duas linhas onde escolher.
 *
 * O `JOIN` com `tenants` é interno de propósito: um canal cujo tenant não
 * exista não é um canal conhecido. A FK da `0001` já o impede, e a consulta não
 * depende disso.
 */
export const SQL_CANAL = `
  SELECT c.tenant_id::text AS tenant_id,
         c.id::text        AS channel_id,
         c.vertical        AS vertical,
         t.plano           AS plano,
         t.estado          AS estado_tenant,
         c.estado          AS estado_canal,
         c.channel_mode    AS channel_mode,
         c.origem          AS origem,
         t.tipo            AS tipo_tenant
    FROM platform.tenant_channels c
    JOIN platform.tenants t ON t.id = c.tenant_id
   WHERE c.phone_number_id = $1
`;

/**
 * A guarda de arranque do ADR-011: conta as linhas de Fluxo B. Como
 * `kamba_resolver`.
 *
 * Uma consulta e não três, ao contrário do espelho Python
 * (`libs/py-core/src/kamba_core/fluxo_piloto.py`), e a razão é a mesma pela
 * qual o espelho usa três: ali cada uma tem a sua descrição na lista
 * `VERIFICACOES`; aqui as três contagens saem numa linha e a mensagem compõe-se
 * no código. **Os números têm de ser os mesmos**, e há um teste que os compara
 * com os do Python contra a mesma base.
 *
 * A terceira contagem é **mais larga** do que o critério de aceitação, que
 * nomeia só `vertical = 'assistente'`: uma comparação por igualdade não via
 * `assistente_v2`. Lista de permitidas, como no espelho.
 */
export const SQL_GUARDA_FLUXO_B = `
  SELECT (SELECT count(*) FROM platform.tenants
           WHERE tipo = $1)                                AS tenants_plataforma,
         (SELECT count(*) FROM platform.tenant_channels
           WHERE origem = $2)                              AS canais_plataforma,
         (SELECT count(*) FROM platform.tenant_channels
           WHERE NOT (vertical = ANY($3::text[])))         AS verticais_fora
`;

/**
 * O papel desta ligação vê **todas** as linhas das duas tabelas?
 *
 * É a mesma pergunta — e a mesma resposta — do `CONSULTA_DE_VISIBILIDADE` do
 * espelho Python, e existe pelo mesmo motivo: a guarda conta linhas, e uma
 * contagem só vale se quem conta vir todas. Com a RLS do KAM-004 (`FORCE`,
 * política por `app.tenant_id`), um papel sem contexto vê **zero** — e a guarda
 * devolveria «pode arrancar» sobre uma base cheia de Fluxo B.
 *
 * Três vias, e basta uma: o papel contorna a RLS; nenhuma das duas tabelas a
 * tem activa; ou o papel tem, **em cada uma das duas**, uma política permissiva
 * de leitura total (`SELECT` ou `ALL`, `USING (true)`) **e** nenhuma restritiva
 * lha estreita. A terceira é a do `kamba_resolver`.
 *
 * O texto é o do espelho, instrução por instrução, e há um teste que compara os
 * dois resultados contra a mesma base. Divergir aqui era ter duas guardas com
 * opiniões diferentes sobre a mesma base.
 */
export const SQL_VISIBILIDADE = `
  SELECT COALESCE((SELECT rolbypassrls OR rolsuper FROM pg_roles
                    WHERE rolname = current_user), false)
      OR NOT EXISTS (SELECT 1 FROM pg_class c
                       JOIN pg_namespace n ON n.oid = c.relnamespace
                      WHERE n.nspname = 'platform'
                        AND c.relname IN ('tenants', 'tenant_channels')
                        AND c.relrowsecurity)
      OR ((SELECT count(DISTINCT tablename) FROM pg_policies
            WHERE schemaname = 'platform'
              AND tablename IN ('tenants', 'tenant_channels')
              AND permissive = 'PERMISSIVE' AND cmd IN ('SELECT', 'ALL')
              AND qual = 'true' AND current_user = ANY(roles)) = 2
          AND NOT EXISTS (SELECT 1 FROM pg_policy p
                            JOIN pg_class c ON c.oid = p.polrelid
                            JOIN pg_namespace n ON n.oid = c.relnamespace
                           WHERE n.nspname = 'platform'
                             AND c.relname IN ('tenants', 'tenant_channels')
                             AND NOT p.polpermissive
                             AND p.polcmd IN ('r', '*')
                             AND (0 = ANY(p.polroles)
                                  OR EXISTS (SELECT 1 FROM unnest(p.polroles) AS papel(oid)
                                              WHERE papel.oid <> 0
                                                AND pg_has_role(current_user, papel.oid, 'MEMBER')))))
        AS ve_tudo
`;

/**
 * Abre ou reabre a conversa de um (tenant, contacto, canal). Como `kamba_app`,
 * **com** contexto de tenant.
 *
 * `ON CONFLICT ... DO UPDATE` sobre a `conversations_tenant_contact_channel_uq`:
 * a primeira mensagem cria a conversa, as seguintes empurram a janela. É o que
 * torna o caminho idempotente — a repetição do mesmo `wamid` não cria uma
 * segunda conversa, porque não há segunda linha onde a criar.
 *
 * **O `mode` não aparece no `SET`**, e não é esquecimento: `kamba_app` não tem
 * `UPDATE (mode)` (revisão `0009`), e uma entrada que chega não muda quem tem a
 * palavra. O que a conversa **devolve** é o `mode` que lá está, e é com ele que
 * o CHR decide se entrega ao AGR ou ao dono.
 *
 * A janela escreve-se com valores vindos de fora (`$4`, `$5`) e não com
 * `now()`: é o relógio injectável que os testes da matriz de estados precisam,
 * e é o mesmo instante que o `window_expires_at` deriva — com dois `now()` numa
 * instrução, o `conversations_janela_ck` continuava satisfeito mas os dois
 * tempos vinham de leituras diferentes do relógio.
 */
export const SQL_ABRIR_CONVERSA = `
  INSERT INTO platform.conversations
         (tenant_id, contact_id, channel_id, last_inbound_at, window_expires_at)
  VALUES ($1, $2, $3, $4, $5)
  ON CONFLICT (tenant_id, contact_id, channel_id) DO UPDATE
     SET last_inbound_at   = EXCLUDED.last_inbound_at,
         window_expires_at = EXCLUDED.window_expires_at
  RETURNING id::text AS id, mode
`;

/**
 * A conversa de um (tenant, contacto, canal), sem a tocar. Como `kamba_app`.
 *
 * Serve o caso em que não há entrada a registar — a matriz de estados nega
 * `registar_entrada` — e ainda assim se precisa de saber o modo.
 */
export const SQL_LER_CONVERSA = `
  SELECT id::text AS id, mode, last_inbound_at
    FROM platform.conversations
   WHERE tenant_id = $1 AND contact_id = $2 AND channel_id = $3
`;

/**
 * As conversas do contacto absorvido numa fusão. Como `kamba_identity`, dentro
 * da transacção da fusão.
 *
 * Devolve, por conversa do absorvido, o canal e os tempos — e o `id` da
 * conversa que o contacto que **fica** já tem nesse canal, se tiver. É esse
 * `LEFT JOIN` que separa os dois casos do gancho: sem colisão, reaponta-se; com
 * colisão, dobram-se os tempos na que fica.
 */
export const SQL_CONVERSAS_A_FUNDIR = `
  SELECT de.id::text                 AS id_de,
         de.channel_id::text         AS channel_id,
         de.last_inbound_at          AS last_inbound_at,
         de.window_expires_at        AS window_expires_at,
         de.last_human_activity_at   AS last_human_activity_at,
         para.id::text               AS id_para,
         para.last_inbound_at        AS para_last_inbound_at,
         para.window_expires_at      AS para_window_expires_at,
         para.last_human_activity_at AS para_last_human_activity_at
    FROM platform.conversations de
    LEFT JOIN platform.conversations para
           ON para.tenant_id  = de.tenant_id
          AND para.channel_id = de.channel_id
          AND para.contact_id = $1
   WHERE de.tenant_id = $2 AND de.contact_id = $3
   ORDER BY de.channel_id
`;

/** Reaponta uma conversa para o contacto que fica. Como `kamba_identity`. */
export const SQL_REPONTAR_CONVERSA = `
  UPDATE platform.conversations SET contact_id = $1 WHERE id = $2
`;

/**
 * Dobra os tempos do absorvido na conversa que fica. Como `kamba_identity`.
 *
 * `GREATEST` com `NULL`: em PostgreSQL, `GREATEST` **ignora** os nulos e
 * devolve o maior dos restantes (ao contrário do SQL padrão), que é
 * exactamente o que se quer — uma conversa sem actividade humana não apaga a
 * actividade humana da outra. A janela fica com a mais tardia das duas, e os
 * dois tempos movem-se juntos para o `conversations_janela_ck` continuar
 * satisfeito.
 */
export const SQL_DOBRAR_CONVERSA = `
  UPDATE platform.conversations
     SET last_inbound_at        = GREATEST(last_inbound_at, $1),
         window_expires_at      = GREATEST(window_expires_at, $2),
         last_human_activity_at = GREATEST(last_human_activity_at, $3)
   WHERE id = $4
`;
