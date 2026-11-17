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
 * ## A suspensão e o encerramento também esquecem (KAM-098)
 *
 * Desde a régua de cobrança (KAM-058) a suspensão por falta de pagamento emite
 * o `tenant.suspended`, e desde o off-boarding (KAM-098) o encerramento emite o
 * `tenant.closed`. São o sentido em que a *cache* falha **aberta**: com o
 * contexto guardado 60 s, o CHR continuava a pôr no AGR as mensagens de um
 * tenant que a base já diz `suspenso` ou `encerrado`. A revisão do off-boarding
 * (`*_offboarding.py`) acrescenta as duas subscrições, e o efeito é o mesmo —
 * esquecer o tenant — porque a decisão de encaminhar é da matriz de estados
 * (`tenantGate`), lida da base na resolução seguinte, e não do evento.
 *
 * O nome do efeito e do erro ficaram os da activação: o `VersaoDaActivacaoError`
 * é citado por nome nas verificações do KAM-092 e do KAM-201, e trocá-lo
 * deixava essas linhas a descrever um erro que não existe.
 */

import type { Efeito } from "../eventos/consumo.ts";
import type { ResolvedorDeCanal } from "./canal.ts";

/** O `consumer` da subscrição: o nome das filas `evt.chr.p<n>` e da marca de consumo. */
export const CONSUMIDOR_DO_CHR = "chr";

/** O evento da activação, o primeiro que este consumidor subscreveu (KAM-201). */
export const TIPO_DA_ACTIVACAO = "tenant.activated";

/**
 * Os eventos que esquecem o tenant na *cache*: a activação (KAM-201), a
 * suspensão (KAM-058) e o encerramento (KAM-098). São as linhas `chr` da
 * `platform.evt_subscricoes` e do `registry/chr.yaml`, e um ensaio confronta as
 * três fontes.
 */
export const TIPOS_QUE_ESQUECEM_O_TENANT: readonly string[] = [
  TIPO_DA_ACTIVACAO,
  "tenant.suspended",
  "tenant.closed",
];

/** As versões do contrato que este consumidor conhece, nos três tipos. A da subscrição é a 1. */
export const VERSOES_DA_ACTIVACAO: readonly number[] = [1];

/** Chegou ao consumidor um evento que ele não sabe tratar. Vai à DLQ pela escada. */
export class VersaoDaActivacaoError extends Error {
  override readonly name = "VersaoDaActivacaoError";

  constructor(tipo: string, versao: number) {
    // O tipo e a versão vêm do envelope e são de domínio fechado no arquivo; o
    // `tenant_id` não entra na mensagem.
    super(`o consumidor do estado do tenant no CHR nao trata ${tipo} v${versao}`);
  }
}

/**
 * O efeito do consumidor, na forma do `Efeito` do `consumir`: esquece o tenant
 * do envelope na *cache*. Não usa a ligação — a marca de consumo é do
 * `consumir`, e o efeito é só memória deste processo.
 */
export function efeitoDaActivacao(resolvedor: Pick<ResolvedorDeCanal, "invalidarTenant">): Efeito {
  return async (_bd, envelope) => {
    if (!TIPOS_QUE_ESQUECEM_O_TENANT.includes(envelope.tipo) || !VERSOES_DA_ACTIVACAO.includes(envelope.versao)) {
      throw new VersaoDaActivacaoError(envelope.tipo, envelope.versao);
    }
    resolvedor.invalidarTenant(envelope.tenant_id);
  };
}
