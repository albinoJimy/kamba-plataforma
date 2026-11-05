/**
 * As cadeias SQL das reservas, confrontadas contra PostgreSQL pelo gate 8.
 *
 * Não são uma cópia de nada: a suite `db/tests_encomendas/` lê estas constantes
 * **deste ficheiro** e corre-as contra a base, pelo `ConsultaDoTypeScript` de
 * `db/tests/base.py`. A razão está escrita no `db/tests_produtos/consultas.py`:
 * uma cópia prova que a cópia funciona, e a revisão adversarial do KAM-009
 * descobriu SQL de biblioteca que nunca corria contra base nenhuma.
 *
 * O `$1` é o `tenant_id` em todas, pela razão que o `../orders/consultas.ts`
 * escreve: o repo-base do KAM-042 **exige** o filtro de tenant imediatamente
 * depois do primeiro `WHERE`, e sem ele a consulta não chega à base
 * (`com_repo_filtro_em_falta_total`). É redundante com a RLS de propósito — o
 * RR-01 de `seguranca/riscos_residuais.md` diz que ela «protege de um `WHERE`
 * esquecido, não de código que escolha o tenant errado».
 *
 * ## O `SQL_RESERVAR` é o critério 1, e **não leva `FOR UPDATE`**
 *
 * Esta é a decisão central do ticket, e é uma medição e não um gosto.
 *
 * Os *Detalhes Técnicos* do bloco dão a reserva atómica como
 * `UPDATE … SET reservada = reservada + :q WHERE quantidade - reservada >= :q`,
 * e os *Testes Requeridos* pedem `FOR UPDATE SKIP LOCKED` — mas isso é para o
 * **varrimento**, que é outra consulta (ver o `SQL_VENCIDAS`). Para a reserva,
 * um `SELECT … FOR UPDATE` seguido de `UPDATE` faz o mesmo trabalho em duas
 * viagens:
 *
 * > Sob `READ COMMITTED` a segunda transacção espera pela primeira na tranca da
 * > linha e **reavalia** o `WHERE` sobre o valor novo dela.
 *
 * É a medição que o `db/tests_encomendas/test_concorrencia.py` do KAM-044 pagou
 * e escreveu para o predicado do estado («o predicado do estado, sozinho,
 * serializa»), e vale letra por letra para a aritmética. Mil tentativas
 * paralelas sobre stock 10 escrevem dez linhas e novecentas e noventa escrevem
 * zero, sem nenhuma esperar por nada.
 *
 * **O que não serializa é ler num comando e escrever noutro com o valor lido**,
 * e é exactamente essa a mutação do canário em
 * `db/tests_encomendas/test_reservas.py`. Sem o predicado dentro do próprio
 * `UPDATE`, mil tentativas sobrevendem — e o `CHECK`
 * `offer_terms_stock_nao_sobrevende_ck` da revisão `0033` é que transforma essa
 * sobrevenda num erro ruidoso em vez de uma promessa falsa.
 *
 * ## O `IS NULL` do lado da quantidade é o critério 8, e não um descuido
 *
 * `stock_quantidade IS NULL OR stock_quantidade - stock_reservada >= $3`. Nulo
 * é «quantidade não declarada», que é o estado de toda a Fase 0 para quem nunca
 * declarou stock — e o critério 8 diz o que isso significa:
 * «`stock_modo='indicativo'` reserva internamente sem promessa de
 * exclusividade». A reserva é contada (o `stock_reservada` sobe) e não é
 * limitada, que é precisamente «sem promessa».
 *
 * Um `garantido` **não** chega aqui sem quantidade: o
 * `offer_terms_stock_garantido_exige_quantidade_ck` da `0033` recusa-o na
 * coluna.
 */

/**
 * Lê os termos de stock de um SKU, para decidir a reserva. **Sem tranca.**
 *
 * O `deleted_at IS NULL` está no predicado e não na aplicação: um SKU sob
 * *soft delete* (§5.6) não se reserva, e deixar isso ao chamador era deixá-lo
 * esquecer-se — a mesma escolha do `SQL_LER` do `../orders/consultas.ts`.
 */
export const SQL_LER_OFERTA = `
  SELECT sku, nome, stock_modo, stock_quantidade, stock_reservada, estado
    FROM platform.offer_terms
   WHERE tenant_id = $1 AND sku = $2 AND deleted_at IS NULL
`;

/**
 * **O critério 1.** Promete `$3` unidades do SKU `$2`, ou não casa linha nenhuma.
 *
 * Ver a nota do módulo para a razão de não levar `FOR UPDATE` e para o que o
 * `IS NULL` significa. O `RETURNING` traz o estado de depois porque quem chama
 * precisa dele para a linha da reserva e para o evento, e uma segunda leitura
 * via a linha de outra transacção.
 */
export const SQL_RESERVAR = `
  UPDATE platform.offer_terms
     SET stock_reservada = stock_reservada + $3,
         atualizado_at = now()
   WHERE tenant_id = $1 AND sku = $2
     AND deleted_at IS NULL
     AND (stock_quantidade IS NULL
          OR stock_quantidade - stock_reservada >= $3)
  RETURNING sku, stock_modo, stock_quantidade, stock_reservada
`;

/**
 * Devolve `$3` unidades ao SKU `$2`. O inverso exacto do `SQL_RESERVAR`.
 *
 * O predicado `stock_reservada >= $3` não é defensivo a mais: é o que impede o
 * `stock_reservada` de descer abaixo de zero se dois *workers* varrerem a mesma
 * reserva. A barreira a sério é o `stock_reservations_estado_terminal` da
 * `0033` — que faz da segunda libertação um não-evento —, e este predicado é a
 * segunda, para o caso de alguém devolver stock sem passar pela reserva.
 *
 * O `offer_terms_stock_reservada_ck` da `0033` é a terceira, e essa não se
 * contorna: a transacção falha.
 */
export const SQL_DEVOLVER_STOCK = `
  UPDATE platform.offer_terms
     SET stock_reservada = stock_reservada - $3,
         atualizado_at = now()
   WHERE tenant_id = $1 AND sku = $2
     AND stock_reservada >= $3
  RETURNING sku, stock_quantidade, stock_reservada
`;

/** As reservas de uma encomenda, pela ordem das linhas. */
export const SQL_LER_RESERVAS = `
  SELECT id, order_id, line_no, sku, qty, estado, motivo, expira_at,
         confirmada_at, version
    FROM platform.stock_reservations
   WHERE tenant_id = $1 AND order_id = $2
   ORDER BY line_no
`;

/**
 * **O critério 5 e o 6, lado `consumida`.** Marca as reservas activas da
 * encomenda.
 *
 * O `estado = 'ativa'` no predicado é a idempotência do critério 4: a segunda
 * chamada casa zero linhas e devolve zero linhas, pelo que quem chama não
 * devolve stock duas vezes. **Não é uma convenção deste módulo** — o *trigger*
 * `stock_reserva_terminal` da `0033` recusa com `KA009` quem o tentasse forçar.
 *
 * O `version = version + 1` satisfaz o `stock_reserva_exige_version`, que
 * levanta `KA008` se a versão não subir.
 */
export const SQL_CONSUMIR = `
  UPDATE platform.stock_reservations
     SET estado = 'consumida',
         consumida_at = now(),
         version = version + 1,
         atualizado_at = now()
   WHERE tenant_id = $1 AND order_id = $2 AND estado = 'ativa'
  RETURNING id, line_no, sku, qty, estado, expira_at, confirmada_at, version
`;

/**
 * **O critério 6, lado `libertada`.** Liberta as reservas activas com motivo.
 *
 * O motivo entra por `$3` e o domínio dele é o
 * `stock_reservations_motivo_ck` da `0033`, que são os três do critério. O
 * `RETURNING` traz `(sku, qty)` porque é o que quem chama precisa para devolver
 * o stock — e traz **só as que mudaram**, que é o que faz da segunda execução
 * um não-evento.
 */
export const SQL_LIBERTAR = `
  UPDATE platform.stock_reservations
     SET estado = 'libertada',
         motivo = $3,
         libertada_at = now(),
         version = version + 1,
         atualizado_at = now()
   WHERE tenant_id = $1 AND order_id = $2 AND estado = 'ativa'
  RETURNING id, line_no, sku, qty, estado, expira_at, confirmada_at, version
`;

/**
 * Liberta **uma** reserva pelo seu `id`, com CAS por `version`.
 *
 * É a forma que o varrimento usa, e a diferença face ao `SQL_LIBERTAR` é o CAS:
 * o *job* repetível e o *delayed job* da mesma reserva podem correr ao mesmo
 * tempo (critério 4), e o `version = $4` faz com que **um** deles escreva. O
 * `estado = 'ativa'` sozinho já serializava por reavaliação do `WHERE`, pela
 * medição do KAM-044; o que o `version` acrescenta é apanhar o ciclo, e aqui
 * não há ciclo possível — uma reserva terminal não volta a `ativa`. Fica
 * **mesmo assim**, porque o custo é zero e porque a propriedade «uma reserva
 * muda uma vez por versão» é o que o `stock_reserva_exige_version` impõe.
 */
export const SQL_LIBERTAR_UMA = `
  UPDATE platform.stock_reservations
     SET estado = 'libertada',
         motivo = $3,
         libertada_at = now(),
         version = version + 1,
         atualizado_at = now()
   WHERE tenant_id = $1 AND id = $2 AND estado = 'ativa' AND version = $4
  RETURNING id, order_id, line_no, sku, qty, estado, version
`;

/**
 * **O critério 3.** O `charge.issued` fixa o `expira_at` e marca a confirmação.
 *
 * O `confirmada_at IS NULL` no predicado é a idempotência: um `charge.issued`
 * entregue duas vezes (o que o EVT permite — entrega é «pelo menos uma vez»)
 * fixa o prazo uma vez. Sem ele, a segunda entrega estendia o prazo outra vez,
 * e uma reserva de 48 h entregue três vezes durava 144 h — acima do tecto de
 * 72 h do critério 7, por um caminho que não passa pelo `extendReservation`.
 */
export const SQL_CONFIRMAR = `
  UPDATE platform.stock_reservations
     SET expira_at = $3::timestamptz,
         confirmada_at = now(),
         version = version + 1,
         atualizado_at = now()
   WHERE tenant_id = $1 AND order_id = $2 AND estado = 'ativa'
     AND confirmada_at IS NULL
  RETURNING id, line_no, sku, qty, expira_at, version
`;

/**
 * **O critério 7.** Prolonga o prazo, e só dentro do tecto.
 *
 * O tecto de 72 h é imposto **duas vezes**, e as duas são necessárias: aqui,
 * contra o `criado_at` da própria reserva, para que a recusa chegue como erro
 * de domínio; e no módulo, que valida o pedido antes de o enviar. O que esta
 * consulta acrescenta ao módulo é que o tecto é medido contra a base e não
 * contra o relógio de quem chama — dois `extendReservation` sucessivos de 36 h
 * cada passavam a validação do módulo um a um e somavam 72 h sobre uma reserva
 * que já tinha 48.
 *
 * O `confirmada_at IS NOT NULL` é a outra metade do critério: «só em
 * `aguarda_pagamento` … e exige cobrança com validade correspondente». Uma
 * reserva provisória não tem cobrança, pelo que não se estende — espera pelo
 * `charge.issued`.
 */
export const SQL_ESTENDER = `
  UPDATE platform.stock_reservations
     SET expira_at = $3::timestamptz,
         version = version + 1,
         atualizado_at = now()
   WHERE tenant_id = $1 AND order_id = $2 AND estado = 'ativa'
     AND confirmada_at IS NOT NULL
     AND $3::timestamptz > expira_at
     AND $3::timestamptz <= criado_at + $4::interval
  RETURNING id, line_no, sku, qty, expira_at, confirmada_at, version
`;

/**
 * **O critério 4.** As reservas vencidas, com `FOR UPDATE SKIP LOCKED`.
 *
 * Aqui o `FOR UPDATE` **é** a escolha certa, ao contrário do `SQL_RESERVAR`, e
 * a razão é que a pergunta é outra: o varrimento não compete pela mesma linha,
 * **reparte** linhas entre *workers*. O `SKIP LOCKED` é o que faz dos «dois
 * *workers* a varrer em simultâneo» dos *Testes Requeridos* dois conjuntos
 * disjuntos em vez de um a esperar pelo outro.
 *
 * **Sem filtro de tenant, e é a única consulta deste módulo assim.** O
 * varrimento corre por toda a base como *job*, com o `kamba_batch`, que tem
 * `BYPASSRLS` por atributo — e por isso **não** passa pelo repo-base, que
 * recusaria a consulta por não ter `tenant_id = $1`. O `tenant_id` sai no
 * `SELECT` porque quem liberta precisa dele para devolver o stock ao SKU certo.
 *
 * O índice que a serve é o `stock_reservations_expira_idx` da `0033`, parcial
 * no `estado = 'ativa'`.
 */
export const SQL_VENCIDAS = `
  SELECT id, tenant_id, order_id, line_no, sku, qty, expira_at, confirmada_at,
         version
    FROM platform.stock_reservations
   WHERE estado = 'ativa' AND expira_at <= $1::timestamptz
   ORDER BY expira_at
   LIMIT $2
     FOR UPDATE SKIP LOCKED
`;

/**
 * A contagem de reservas activas por tenant: a caixa 5 da Definition of Done.
 *
 * Sem filtro de tenant, pela razão do `SQL_VENCIDAS`: é uma medida de
 * plataforma, lida pelo `kamba_batch`. O que ela **não** é é uma consulta de
 * aplicação — um papel sujeito a RLS que a corresse via só o seu tenant, e a
 * métrica saía com o valor de quem a pediu.
 */
export const SQL_ACTIVAS_POR_TENANT = `
  SELECT tenant_id, count(*) AS activas
    FROM platform.stock_reservations
   WHERE estado = 'ativa'
   GROUP BY tenant_id
   ORDER BY tenant_id
`;

/**
 * O `reservation_release_lag` do critério 4: o atraso de cada libertação.
 *
 * Mede-se **sobre a base e não no processo**, e a diferença é o que o critério
 * pede: «p99 ≤ 60 s» é sobre o intervalo entre o instante em que a reserva
 * venceu e o instante em que foi libertada, e o processo que a libertou só sabe
 * do segundo. Um *job* que arrancasse atrasado media zero e dizia que estava
 * dentro do prazo.
 *
 * Em segundos, e não em milissegundos: o critério está em segundos, e o
 * `EXTRACT(EPOCH …)` devolve segundos com fracção.
 */
export const SQL_ATRASO_DA_LIBERTACAO = `
  SELECT EXTRACT(EPOCH FROM (libertada_at - expira_at)) AS atraso_s
    FROM platform.stock_reservations
   WHERE estado = 'libertada' AND motivo = 'expirada'
     AND libertada_at >= $1::timestamptz
   ORDER BY atraso_s
`;

/**
 * As que a suite exercita contra a base, para o ensaio de cobertura do contrato.
 *
 * **Nos dois sentidos**, como o `EXERCITADAS` do `db/tests_encomendas/`: uma
 * consulta do módulo que ninguém exercite entra sem ser provada, e um nome
 * nesta lista que o módulo não tenha é uma declaração morta. Foi assim que o
 * `SQL_GRELHA` do KAM-047 chegou com um defeito que nenhuma bateria tocava.
 */
export const CONSULTAS_DAS_RESERVAS = [
  "SQL_LER_OFERTA",
  "SQL_RESERVAR",
  "SQL_DEVOLVER_STOCK",
  "SQL_LER_RESERVAS",
  "SQL_CONSUMIR",
  "SQL_LIBERTAR",
  "SQL_LIBERTAR_UMA",
  "SQL_CONFIRMAR",
  "SQL_ESTENDER",
  "SQL_VENCIDAS",
  "SQL_ACTIVAS_POR_TENANT",
  "SQL_ATRASO_DA_LIBERTACAO",
] as const;
