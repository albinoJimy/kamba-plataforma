/**
 * O consumidor do `tenant.activated` no CHR (KAM-092, critério 7): a activação
 * esquece o tenant na *cache* do `ResolvedorDeCanal`.
 *
 * ## Porque é que a activação invalida, se a *cache* já falha fechada
 *
 * O CHR não encaminha um tenant em `onboarding` (a matriz do KAM-014 dá-lhe o
 * regime `pendente`). Com o contexto guardado 60 s por `phone_number_id`, a
 * primeira mensagem depois da activação ainda podia ler o `onboarding` da
 * *cache*, e o dono que acabou de ligar a loja ficava até um minuto sem
 * resposta. A invalidação é **por tenant** e não por canal: o evento traz o
 * `tenant_id` no envelope, e não o `phone_number_id`, que é a chave da *cache*.
 *
 * ## O efeito não lê a base, e a versão desconhecida falha
 *
 * O efeito corre dentro do `consumir` do KAM-006, que marca o evento consumido
 * na mesma transacção — e o efeito é só memória deste processo. Uma versão que
 * este consumidor não conhece **lança** (`VersaoDaActivacaoError`): o `consumir`
 * recua pela escada e, esgotadas as tentativas, põe o evento na DLQ. Uma versão
 * nova engolida em silêncio era uma activação que o CHR nunca via.
 *
 * ## Quem entrega o evento, e a quem
 *
 * A subscrição `chr`/`tenant.activated` v1 em `platform.evt_subscricoes` (a
 * revisão de dados do KAM-201, declarada em `registry/chr.yaml`) faz o
 * publicador pôr o evento nas dezasseis filas `evt.chr.p<n>`, e o processo do
 * CHR (`services/worker-canal/src/entrada.ts`) serve-as com este efeito.
 *
 * **Uma réplica, e só uma, recebe cada evento**: as filas são de consumidores
 * concorrentes. Com o processo do CHR em mais de uma réplica, as outras
 * continuam com a *cache* velha até ao TTL — no sentido que falha fechado. Uma
 * invalidação em todas pedia difusão (*pub/sub*), e não existe.
 *
 * E só a activação invalida: a suspensão e o encerramento — o sentido em que a
 * *cache* falha **aberta** — não são emitidos ainda (dicionário §3.70).
 */

import type { Efeito } from "../eventos/consumo.ts";
import type { ResolvedorDeCanal } from "./canal.ts";

/** O `consumer` da subscrição: o nome das filas `evt.chr.p<n>` e da marca de consumo. */
export const CONSUMIDOR_DO_CHR = "chr";

/** O evento que este consumidor subscreve. */
export const TIPO_DA_ACTIVACAO = "tenant.activated";

/** As versões do contrato que este consumidor conhece. A da subscrição é a 1. */
export const VERSOES_DA_ACTIVACAO: readonly number[] = [1];

/** Chegou ao consumidor um evento que ele não sabe tratar. Vai à DLQ pela escada. */
export class VersaoDaActivacaoError extends Error {
  override readonly name = "VersaoDaActivacaoError";

  constructor(tipo: string, versao: number) {
    // O tipo e a versão vêm do envelope e são de domínio fechado no arquivo; o
    // `tenant_id` não entra na mensagem.
    super(`o consumidor da activacao do CHR nao trata ${tipo} v${versao}`);
  }
}

/**
 * O efeito do consumidor, na forma do `Efeito` do `consumir`: esquece o tenant
 * do envelope na *cache*. Não usa a ligação — a marca de consumo é do
 * `consumir`, e o efeito é só memória deste processo.
 */
export function efeitoDaActivacao(resolvedor: Pick<ResolvedorDeCanal, "invalidarTenant">): Efeito {
  return async (_bd, envelope) => {
    if (envelope.tipo !== TIPO_DA_ACTIVACAO || !VERSOES_DA_ACTIVACAO.includes(envelope.versao)) {
      throw new VersaoDaActivacaoError(envelope.tipo, envelope.versao);
    }
    resolvedor.invalidarTenant(envelope.tenant_id);
  };
}
