/**
 * Arquivar a conta de atendimento de um *tenant* (KAM-233): a conta que o
 * `ensureAccount` criou, lida da `handoff_accounts`, suspensa no provedor.
 *
 * Uma função, e não só o método da `Handoff`, porque quem arquiva é o
 * encerramento, no processo de lote, que não monta o HND inteiro (a fila do
 * espelho, a retoma, o cliente de execução). A `Handoff.archiveAccount` chama
 * esta mesma função: um só caminho para as duas portas.
 *
 * A conta não está no `provisioning_step`: nasce na primeira passagem a humano
 * (`ensureAccount`), e não na saga. Por isso a revogação lê-a daqui, e um
 * *tenant* que nunca passou a humano não tem conta — `sem_conta`, sem pedido
 * nenhum ao provedor.
 */

import { SQL_CONTA } from "./consultas.ts";
import type { ArquivoDoProvedor, ClienteSql, DesfechoDoArquivo, Provedor } from "./contrato.ts";

export async function arquivarContaDoTenant(o: {
  readonly bd: Pick<ClienteSql, "query">;
  readonly arquivo: ArquivoDoProvedor;
  readonly tenantId: string;
  readonly provedor: Provedor;
}): Promise<DesfechoDoArquivo | "sem_conta"> {
  const { rows } = await o.bd.query(SQL_CONTA, [o.tenantId, o.provedor]);
  const linha = rows[0];
  if (linha === undefined) return "sem_conta";
  return o.arquivo.arquivarConta(Number(linha.account_id));
}
