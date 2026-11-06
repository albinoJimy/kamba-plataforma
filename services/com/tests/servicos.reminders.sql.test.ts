/**
 * As duas consultas próprias do lembrete (KAM-048, critério 8).
 *
 * ## O que este ficheiro é, e o que ele **não** é
 *
 * **Não é a consulta a correr.** Nenhum motor executa estas cadeias hoje — não
 * há suite de *gate* 8 para este ticket, pela razão e com o credor escritos na
 * nota de `reminders/consultas.ts`. Uma asserção sobre o **texto** de uma
 * consulta não apanha um erro de sintaxe, um tipo errado nem um plano mau, e o
 * estado disto quanto a execução é **NÃO VERIFICADO**.
 *
 * O que ele é: a rede que prende os perigos **concretos** que a revisão
 * adversarial explorou por mutação e que ficaram verdes por não haver medição
 * nenhuma — `ELSE 4000` posto a `ELSE 999999`, e o `NULLS LAST` removido. Cada
 * asserção abaixo corresponde a uma dessas mutações, ou a um defeito que a
 * revisão encontrou por leitura.
 *
 * Vale a pena dizer porque é texto e não execução: as colunas e os tipos **estão**
 * lidos contra o inventário de `db/tests/test_inventario.py`, e o que falta é
 * um motor. Prender o texto é o que se pode fazer sem alargar as listas fechadas
 * da suite `tests_outbound`, que é de outro ticket.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { TERMINAIS } from "@kamba/core-ts/outbound";

import {
  PADRAO_DE_LEMBRETE,
  SQL_CUSTO_DOS_LEMBRETES,
  SQL_DESTINO,
  SQL_LEMBRETES_DO_TENANT,
} from "../src/servicos/reminders/index.ts";

test("o padrao isola os lembretes pelo segmento da chave, e nao pela etiqueta", () => {
  // O que identifica um lembrete e o `:reminder:` do criterio 2, e **nao** o
  // `T-24h`: um padrao com a etiqueta deixava de contar os lembretes antigos no
  // dia em que a antecedencia fosse calibrada, e o painel mostrava uma queda que
  // nao aconteceu.
  assert.equal(PADRAO_DE_LEMBRETE, "%:reminder:%");
  assert.ok(!PADRAO_DE_LEMBRETE.includes("T-24h"));
});

test("o destino ordena com NULLS LAST", () => {
  // **Mutacao M6 da revisao adversarial: removido, os 52 ensaios ficavam
  // verdes.** Em PostgreSQL um `NULL` ordena **primeiro** num `DESC`, pelo que
  // sem ele uma conversa que nunca recebeu nada ganhava a uma que falou ontem —
  // e o lembrete saia sempre por *template* pago, com a janela aberta ao lado.
  assert.match(SQL_DESTINO, /ORDER BY\s+c\.last_inbound_at DESC NULLS LAST/);
  assert.match(SQL_DESTINO, /LIMIT 1/);
  // E o `tenant_id` esta no predicado **alem** da RLS, pela razao do
  // `SQL_JANELA` do KAM-015: a consulta fica correcta mesmo corrida sem
  // contexto, devolvendo zero linhas em vez das de outro.
  assert.match(SQL_DESTINO, /c\.tenant_id = \$1/);
});

test("o estado do canal nao se filtra no destino", () => {
  // Quem decide se um canal `restrito` ou `suspenso` envia e a matriz do
  // KAM-009, por dentro do `Saida` (`STATE_REFUSED`). Filtrar aqui dava
  // `SEM_CONVERSA` para um canal suspenso — o motivo errado, e o que o painel
  // precisa de ver e o estado.
  assert.ok(!/tc\.estado/.test(SQL_DESTINO));
});

test("os falhados cobrem os dois estados terminais, por parametro", () => {
  // **A primeira versao contava `state = 'failed'` e mais nada.** Os terminais
  // sao dois, e os dois querem dizer «nao saiu mensagem»: uma linha
  // `suppressed_by_human` entrava em `tentados`, ficava fora de `falhados` e
  // dava custo zero — lia-se como um lembrete entregue e gratis. Combinado com o
  // defeito do `turnoIniciadoEm`, era o estado de **todas** as linhas em
  // producao, e o painel diria «N tentados, 0 falhados, 0 custo» com zero
  // lembretes enviados.
  assert.match(SQL_LEMBRETES_DO_TENANT, /state = ANY\(\$5\)/);
  assert.ok(!/state = 'failed'/.test(SQL_LEMBRETES_DO_TENANT));
  // O dominio tem **um** dono: quem chama passa os `TERMINAIS` do KAM-015.
  assert.deepEqual([...TERMINAIS], ["failed", "suppressed_by_human"]);
});

test("nenhuma das consultas converte categorias em dinheiro", () => {
  // **Mutacao M5 da revisao: `ELSE 4000` posto a `ELSE 999999` ficava verde.**
  // Tres defeitos numa linha: um `ELSE` nao-nulo facturava uma categoria
  // desconhecida (e a Meta acrescenta categorias), o `billable` ausente passava
  // pelo `CASE` em vez de ser excluido, e os literais eram uma **terceira** copia
  // das tarifas, nao comparada com nada — as duas que existem sao confrontadas
  // como texto pelo `TestTarifas` de `db/tests_outbound/test_outbound.py`.
  //
  // A correccao e nao converter: conta-se por categoria e quem chama multiplica
  // pelo `microUsdDe` do KAM-015, que e o unico sitio desta casa onde uma
  // categoria se torna um numero — e o que recusa uma que nao conhece.
  for (const consulta of [SQL_LEMBRETES_DO_TENANT, SQL_CUSTO_DOS_LEMBRETES]) {
    assert.ok(!/\b4000\b/.test(consulta), "tarifa literal numa consulta deste modulo");
    assert.ok(!/\b22500\b/.test(consulta), "tarifa literal numa consulta deste modulo");
    assert.ok(!/\bELSE\b/.test(consulta), "um CASE com ELSE converte o desconhecido");
  }
  assert.match(SQL_CUSTO_DOS_LEMBRETES, /pricing->>'category' AS categoria/);
});

test("o custo exclui o nao facturavel no WHERE, e nao num CASE", () => {
  // `WHEN NOT (pricing->>'billable')::boolean THEN 0` nao excluia nada com o
  // `billable` **ausente**: a condicao e `NULL`, o `CASE` seguia para o `ELSE` e
  // a linha era cobrada. O KAM-015 poe o predicado no `WHERE`, que exclui — e e
  // essa a forma que se copia.
  assert.match(SQL_CUSTO_DOS_LEMBRETES, /AND \(pricing->>'billable'\)::boolean/);
  assert.match(SQL_CUSTO_DOS_LEMBRETES, /AND pricing IS NOT NULL/);
});

test("o custo soma na entrega e a contagem soma na criacao", () => {
  // **A cobranca e na entrega** (`E1` §1, CONFIRMADO), pelo que o custo filtra
  // por `delivered_at`, como o `SQL_CUSTO_DO_TENANT` do KAM-015. A primeira
  // versao somava por `created_at`: uma mensagem criada no dia 1 e entregue no
  // dia 2 caia no periodo errado, e os dois paineis discordavam.
  assert.match(SQL_CUSTO_DOS_LEMBRETES, /delivered_at >= \$2/);
  assert.match(SQL_CUSTO_DOS_LEMBRETES, /delivered_at < \$3/);
  // A contagem de **tentativas**, essa, e por `created_at` de proposito: a
  // pergunta e «quantos lembretes tentamos», e uma mensagem em `queued` e uma
  // tentativa — a mesma leitura que o `SQL_AVISOS_ENVIADOS` do KAM-022 faz.
  assert.match(SQL_LEMBRETES_DO_TENANT, /created_at >= \$2/);
  assert.ok(!/delivered_at/.test(SQL_LEMBRETES_DO_TENANT));
});

test("as duas consultas sao parametrizadas e levam o tenant no predicado", () => {
  for (const consulta of [SQL_DESTINO, SQL_LEMBRETES_DO_TENANT, SQL_CUSTO_DOS_LEMBRETES]) {
    assert.match(consulta, /tenant_id = \$1/);
    // Nenhuma interpolacao: um `${` numa cadeia de SQL deste modulo seria
    // concatenacao de valores, que e o que a parametrizacao existe para impedir.
    assert.ok(!consulta.includes("${"));
  }
});
