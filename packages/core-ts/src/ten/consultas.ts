/**
 * O SQL do TEN, num sitio so (KAM-009, revisao `0007`).
 *
 * Separado do resto pela mesma razao que o `eventos/consultas_consumo.ts`:
 * para se poder ler o SQL sem ler o codigo a volta, e para o espelho em Python
 * (`kamba_core.ten.consultas`) poder ser comparado **como texto** por uma
 * maquina em vez de por uma promessa em prosa. O teste que os confronta e o
 * `TestParidadeDoTypeScript` de `libs/py-core/tests/test_ten.py`.
 *
 * ## A aritmetica nao esta aqui, e isso e o ponto
 *
 * Nenhuma destas consultas soma, subtrai ou compara um limite. A regra —
 * «quanto ja gastou, qual e o tecto, cabe mais?» — vive **inteira** na funcao
 * `platform.ten_consumir` da revisao `0007`, e as duas bibliotecas chamam-na.
 * Duas implementacoes da mesma aritmetica de limites divergem; o bloco do
 * ticket pede «o Python chama a mesma regra SQL» e o mesmo argumento vale para
 * o TypeScript. O que esta aqui sao chamadas e leituras.
 *
 * O mesmo vale para o mes: o periodo e `platform.ten_periodo`, e nao um
 * `date_trunc` reescrito em JavaScript. O fuso `Africa/Luanda` existe **num**
 * sitio (o comentario da `0007` di-lo por extenso), e uma terceira copia dele
 * em TypeScript era a quarta a divergir no dia em que uma mudasse.
 *
 * ## A ordem dos parametros segue o texto, e isso e uma restricao real
 *
 * O espelho em Python usa marcadores posicionais (`%s`), e o teste de paridade
 * reescreve os `$n` daqui para `%s` antes de comparar. Um `$2` que apareca no
 * texto **antes** do `$1` sobrevive a comparacao e troca os argumentos no lado
 * Python, em silencio. Por isso os numeros aqui sao sempre ascendentes na
 * ordem de leitura — e e por isso que o `SQL_ENTITLEMENT` filtra o tenant numa
 * subconsulta em vez de o filtrar no `WHERE` final, que o poria depois do
 * `modulo` do `JOIN`.
 *
 * **Tudo parametrizado.** A biblioteca corre como `kamba_app`, sujeita a RLS,
 * mas a ToolLayer tambem a pode chamar de um processo de retaguarda; uma
 * interpolacao aqui lia os limites de todos os tenants no dia em que alguem a
 * chamasse com o papel errado.
 */

/**
 * O periodo de um instante: o primeiro dia do mes em `Africa/Luanda`.
 *
 * Nao se usa para decidir nada — quem decide e a `ten_consumir`, que chama a
 * mesma funcao la dentro. Existe para quem precisa de **mostrar** o periodo
 * (um painel, uma mensagem ao dono) e para os testes de fronteira de mes
 * poderem perguntar a base o que ela conta, com o relogio fixo do criterio 5.
 */
export const SQL_PERIODO = `
  SELECT platform.ten_periodo($1) AS periodo
`;

/**
 * O entitlement de um modulo, e se ele permite.
 *
 * **A decisao vem da base, e nao de um `if` em cada linguagem.** A coluna
 * `permitido` e a conjuncao do criterio 2 do bloco escrita em SQL: ha linha,
 * `ativo` e verdadeiro, e o estado do tenant nao e `onboarding`, `suspenso`
 * nem `encerrado`. Escreve-la aqui, uma vez, e o que faz com que o TypeScript
 * e o Python nao possam discordar — e e o mesmo argumento da `0007` para a
 * aritmetica dos limites, aplicado a uma regra mais pequena.
 *
 * **Zero linhas tambem e uma decisao: nega.** Nao ha linha quando o tenant nao
 * existe, quando esta apagado por `deleted_at`, e — o caso que importa — quando
 * o contexto de RLS e de **outro** tenant: a politica `tenant_iso` de
 * `platform.tenants` e `id = app.tenant_id`, e um contexto trocado devolve
 * vazio em vez de erro. Quem le isto trata o vazio como negado, e nao como
 * «nao sei».
 *
 * O `LEFT JOIN` e deliberado: um tenant `suspenso` sem linha de entitlement e
 * um tenant `ativo` sem linha de entitlement tem de ser distinguiveis no
 * registo de quem nega, e com um `INNER JOIN` os dois davam zero linhas. O
 * `tem_linha` e o que distingue «nao ha entitlement» de «ha, e esta inactivo»:
 * sem ele o `coalesce(e.ativo, false)` tornava os dois casos no mesmo `false`,
 * e quem nega ficava sem saber se falta provisionamento (KAM-091) ou se alguem
 * desligou o modulo.
 *
 * Parametros: `$1` o tenant, `$2` o modulo.
 */
export const SQL_ENTITLEMENT = `
  SELECT t.estado AS estado_tenant,
         (e.tenant_id IS NOT NULL) AS tem_linha,
         coalesce(e.ativo, false) AS ativo,
         (    t.estado <> ALL (ARRAY['onboarding', 'suspenso', 'encerrado'])
          AND coalesce(e.ativo, false)) AS permitido
    FROM (SELECT id, estado
            FROM platform.tenants
           WHERE id = $1 AND deleted_at IS NULL) AS t
    LEFT JOIN platform.entitlements AS e
           ON e.tenant_id = t.id AND e.modulo = $2
`;

/**
 * O consumo: a chamada a regra unica.
 *
 * Os seis argumentos sao os da assinatura da `0007`, pela ordem:
 * `$1` tenant, `$2` chave de limite, `$3` quantidade, `$4` chave de
 * idempotencia, `$5` tecto de quem chama (ou `NULL`) e `$6` o instante (ou
 * `NULL` para `now()`).
 *
 * Os dois ultimos passam-se **sempre**, com `NULL` quando nao ha valor, em vez
 * de se montarem duas versoes do texto consoante os argumentos. Duas versoes
 * seriam duas consultas a manter e a comparar com o Python, e a que se usa
 * menos e a que se parte.
 *
 * `coalesce($6, now())` em vez de deixar o `DEFAULT` da funcao resolver: um
 * argumento nomeado ausente nao se exprime numa chamada posicional, e passar
 * `NULL` a secas poria o periodo a `NULL` e o `CHECK` de `tenant_usage` a
 * recusar tudo.
 */
export const SQL_CONSUMIR = `
  SELECT aceite, valor, repetido, limite
    FROM platform.ten_consumir($1, $2, $3, $4, $5, coalesce($6, now()))
`;
