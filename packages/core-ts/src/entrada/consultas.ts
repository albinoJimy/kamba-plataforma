/**
 * O SQL da entrada de canal (KAM-013), num ficheiro só.
 *
 * Está separado do `registo.ts` pela mesma razão que o
 * `eventos/consultas_consumo.ts` está separado do `consumo.ts`: a suite de base
 * de dados (`db/tests_entrada/`) lê estas constantes **deste ficheiro** e
 * exercita-as contra um PostgreSQL real, pela classe `ConsultaDoTypeScript` de
 * `db/tests/base.py`. Uma cópia do SQL no teste provava que a cópia funciona.
 *
 * **Os marcadores são `$n` e a ordem em que aparecem no texto importa**: o
 * `pg8000` da suite Python não tem `$n`, tem `%s`, e liga-os pela ordem de
 * aparição. A `ConsultaDoTypeScript` reordena, mas só se a numeração for
 * contígua a partir de 1.
 */

/**
 * Registra um evento de canal, ou não faz nada se já estava registado.
 *
 * `ON CONFLICT (kind, event_key) DO NOTHING RETURNING id` é o segundo nível de
 * deduplicação do critério 4: o `jobId` do GWY apanha a re-entrega byte-a-byte,
 * e isto apanha a mesma mensagem embrulhada em dois corpos diferentes.
 *
 * **Uma linha devolvida significa «nova e por encaminhar»**; zero linhas
 * significa «já cá estava», e nesse caso quem chama pergunta pelo
 * `SQL_POR_ENCAMINHAR` antes de decidir que não há nada a fazer — ver a
 * docstring do `registo.ts`.
 *
 * O `RETURNING id` é a razão por que `kamba_app` tem `SELECT` nesta tabela: o
 * PostgreSQL exige-o na coluna devolvida.
 */
export const SQL_REGISTAR = `
  INSERT INTO platform.inbound_events (kind, event_key, waba_id, phone_number_id)
  VALUES ($1, $2, $3, $4)
  ON CONFLICT (kind, event_key) DO NOTHING
  RETURNING id
`;

/**
 * O `id` de um evento que já está registado e **ainda não foi encaminhado**.
 *
 * Existe por causa de uma janela real: registar e encaminhar não são atómicos —
 * o encaminhamento sai deste processo —, e um `kill -9` entre os dois deixava
 * um evento registado que ninguém tratou. Na entrega seguinte, o `ON CONFLICT`
 * não devolve linha e, sem esta consulta, o *worker* concluía «duplicado» e o
 * evento perdia-se **em silêncio**, que é a pior forma de o perder.
 *
 * É também a razão de a coluna `processado_at` existir, e de ser a **única**
 * que `kamba_app` pode actualizar.
 */
export const SQL_POR_ENCAMINHAR = `
  SELECT id FROM platform.inbound_events
  WHERE kind = $1 AND event_key = $2 AND processado_at IS NULL
`;

/** Marca o evento como encaminhado. A única escrita de `kamba_app` depois do registo. */
export const SQL_MARCAR_ENCAMINHADO = `
  UPDATE platform.inbound_events SET processado_at = now() WHERE id = $1
`;

/**
 * Põe um evento em quarentena, ou não faz nada se já lá estava.
 *
 * **Sem `RETURNING`**, e isso é desenho e não esquecimento: `kamba_app` não tem
 * `SELECT` nesta tabela (a coluna `payload` pode levar telefone e texto de
 * mensagem, e quem escreve não precisa de ler — o mesmo que o `audit_log` do
 * KAM-012). A quarentena não tem de distinguir uma entrada nova de um
 * duplicado; basta não duplicar.
 */
export const SQL_QUARENTENA = `
  INSERT INTO platform.unrouted_events
         (kind, event_key, waba_id, phone_number_id, motivo, payload)
  VALUES ($1, $2, $3, $4, $5, $6)
  ON CONFLICT (kind, event_key) DO NOTHING
`;
