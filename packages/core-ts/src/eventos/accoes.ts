/**
 * Efeitos fora da base de dados, uma só vez — o `once(key, fn)` do §6.3.
 *
 * ## O problema que isto resolve, e que a transacção não resolve
 *
 * O consumo é idempotente porque a marca e o efeito partilham a transacção
 * (`consumo.ts`). Um efeito **externo** — mandar uma mensagem no WhatsApp,
 * chamar um HTTP de terceiro — não entra nessa transacção: acontece no mundo, e
 * o mundo não faz `ROLLBACK`. Sem registo próprio, uma re-entrega manda a
 * mensagem outra vez.
 *
 * A tabela `evt_acoes` é esse registo, com a chave
 * `consumer:event_id:acção` — **a mesma** que vai no `Idempotency-Key` do
 * pedido ao terceiro, para que quem o recebe possa também deduplicar.
 *
 * ## Os três estados, e porque `em_curso` existe
 *
 *     em_curso   registada, a correr. O processo pode morrer aqui.
 *     feita      correu, com o resultado guardado.
 *     falhada    correu e falhou de forma definitiva.
 *
 * O caso que decide o desenho é o terceiro: **o processo morreu entre o registo
 * e a conclusão**. O efeito talvez tenha acontecido — a mensagem pode ter saído
 * e a resposta perdeu-se. Repetir é arriscar duas mensagens ao cliente; marcar
 * como feita é arriscar nenhuma. Nenhuma das duas se escolhe em silêncio:
 * `once` **adia**, e quem decide é quem lê o registo (ou o terceiro, pela chave
 * de idempotência que recebeu).
 *
 * É a mesma escolha que o KAM-005 fez na `PROVA INVALIDA` da prova por mutação:
 * entre afirmar o que não se sabe e dizer «não sei», diz-se «não sei».
 */

import {
  SQL_ABRIR_ACCAO,
  SQL_FECHAR_ACCAO,
  SQL_LER_ACCAO,
} from './consultas_consumo.ts';
import { Adiar } from './consumo.ts';
import type { ClienteSql } from './publicador.ts';

/** O nome de uma acção: `[a-z][a-z0-9_]{1,30}`, para a chave ser legível. */
const NOME_DA_ACCAO = /^[a-z][a-z0-9_]{1,30}$/;

/** Estados de uma acção externa, como o DDL os declara. */
export const ESTADOS_DE_ACCAO = ['em_curso', 'feita', 'falhada'] as const;
export type EstadoDeAccao = (typeof ESTADOS_DE_ACCAO)[number];

export class AccaoInvalidaError extends Error {
  readonly accao: string;

  constructor(accao: string) {
    super(`nome de acção inválido: ${JSON.stringify(accao)}`);
    this.name = 'AccaoInvalidaError';
    this.accao = accao;
  }
}

/**
 * A chave de idempotência de uma acção: `consumer:event_id:acção`.
 *
 * A forma é do §6.3 e vai no cabeçalho `Idempotency-Key`. O `consumer` e a
 * `accao` são validados; o `event_id` vem do envelope, que o `lerEnvelope` já
 * validou como UUID.
 */
export function chaveDaAccao(consumer: string, eventId: string, accao: string): string {
  if (!NOME_DA_ACCAO.test(accao)) throw new AccaoInvalidaError(accao);
  if (!NOME_DA_ACCAO.test(consumer)) throw new AccaoInvalidaError(consumer);
  return `${consumer}:${eventId}:${accao}`;
}

export interface OpcoesDaAccao {
  readonly bd: ClienteSql;
  readonly consumer: string;
  readonly eventId: string;
  readonly tenantId: string;
  readonly accao: string;
}

export interface ResultadoDaAccao<T> {
  /** `true` se foi esta chamada que executou o efeito. */
  readonly executou: boolean;
  /** O resultado: o desta execução, ou o que ficou guardado da primeira. */
  readonly resultado: T | null;
}

/**
 * Corre `fn` uma só vez para esta chave, e devolve o resultado guardado nas
 * chamadas seguintes.
 *
 * **Não** corre dentro da transacção do consumo, e é de propósito: um efeito
 * externo que ficasse pendurado seguraria a transacção (e os seus *locks*) pelo
 * tempo de uma chamada de rede. Por isso `once` abre e fecha a sua própria
 * transacção curta em cada passo, e o `fn` corre **entre** as duas.
 *
 * Lança `Adiar` quando encontra a chave `em_curso`: ou outro processo está a
 * correr o efeito agora, ou um morreu a meio. Nos dois casos, a resposta certa
 * é tentar outra vez mais tarde — e no segundo, alguém tem de olhar.
 */
export async function once<T>(
  opcoes: OpcoesDaAccao,
  fn: () => Promise<T>,
): Promise<ResultadoDaAccao<T>> {
  const { bd, consumer, eventId, tenantId, accao } = opcoes;
  const chave = chaveDaAccao(consumer, eventId, accao);

  const abriu = await bd.query(SQL_ABRIR_ACCAO, [chave, consumer, eventId, accao, tenantId]);
  if ((abriu.rowCount ?? 0) === 0) {
    const { rows } = await bd.query(SQL_LER_ACCAO, [chave]);
    const estado = rows[0]?.estado as EstadoDeAccao | undefined;
    if (estado === 'em_curso') {
      throw new Adiar(
        5,
        `a acção ${chave} está em curso: outro processo corre-a agora, ou morreu a meio`,
      );
    }
    // `feita` ou `falhada`: já se decidiu, e não se repete. Devolve-se o que
    // ficou guardado — incluindo `null`, que é o resultado de quem não guardou
    // nada.
    return { executou: false, resultado: (rows[0]?.resultado ?? null) as T | null };
  }

  let resultado: T;
  try {
    resultado = await fn();
  } catch (erro) {
    // A acção fica `falhada` **com** o motivo: sem isto, a chave ficava
    // `em_curso` para sempre e todas as re-entregas adiavam — o efeito nunca
    // acontecia e ninguém sabia porquê.
    const motivo = erro instanceof Error ? erro.message : String(erro);
    await bd.query(SQL_FECHAR_ACCAO, [chave, 'falhada', JSON.stringify({ erro: motivo })]);
    throw erro;
  }
  await bd.query(SQL_FECHAR_ACCAO, [
    chave,
    'feita',
    resultado === undefined ? null : JSON.stringify(resultado),
  ]);
  return { executou: true, resultado };
}
