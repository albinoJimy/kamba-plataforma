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
 *
 * ## A ligação **não** pode ser a do consumo
 *
 * Isto corre fora da transacção do consumo, e a palavra «fora» é literal: o
 * PostgreSQL não tem transacções encadeadas, pelo que um `BEGIN` desta função
 * dentro de uma transacção aberta é um aviso e mais nada — e o `COMMIT`
 * seguinte fecha a transacção de quem chamou. Chamada de dentro do
 * `consumir()`, esta função confirmaria a marca de `events_consumed` **antes
 * de o efeito existir**: uma falha a seguir deixava o evento marcado como
 * consumido e sem efeito, e toda a re-entrega passava a ler «duplicado». O
 * efeito nunca mais acontecia, não havia entrada na DLQ e o reconciliador
 * saltava-o. Num `payment.*`, é cliente que pagou e nunca é confirmado.
 *
 * Por isso a primeira coisa que o `once()` faz é **recusar** uma ligação que
 * já tenha transacção aberta (`TransaccaoAlheiaError`). O lugar certo de um
 * efeito externo é depois do `COMMIT` do consumo, noutra ligação; hoje o laço
 * do consumidor não tem esse lugar — o esqueleto não tem efeitos externos — e
 * isso está registado em `docs/consumo.md` §9.
 */

import {
  SQL_ABRIR_ACCAO,
  SQL_DEFINIR_TENANT,
  SQL_FECHAR_ACCAO,
  SQL_LER_ACCAO,
  SQL_TRANSACCAO_ABERTA,
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
 * O `once()` foi chamado numa ligação que já tem transacção aberta.
 *
 * É erro, e alto, porque a alternativa é pior do que uma falha: o PostgreSQL
 * não tem transacções encadeadas, e o `COMMIT` do `once()` confirmaria a
 * transacção de quem o chamou — a do consumo, com a marca de
 * `events_consumed` lá dentro e sem o efeito feito.
 */
export class TransaccaoAlheiaError extends Error {
  readonly chave: string;

  constructor(chave: string) {
    super(
      `once(${chave}) foi chamado dentro de uma transacção aberta. O PostgreSQL ` +
        'não encadeia transacções: o COMMIT desta função fecharia a de quem a ' +
        'chamou, confirmando a marca de consumo sem o efeito. Um efeito externo ' +
        'corre **depois** do COMMIT do consumo, noutra ligação (docs/consumo.md §8)',
    );
    this.name = 'TransaccaoAlheiaError';
    this.chave = chave;
  }
}

/** Recusa, alto, uma ligação que já esteja em transacção. */
async function exigirForaDeTransaccao(bd: ClienteSql, chave: string): Promise<void> {
  const { rows } = await bd.query(SQL_TRANSACCAO_ABERTA);
  if (rows[0]?.aberta === true) throw new TransaccaoAlheiaError(chave);
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
 *
 * Cada uma dessas duas transacções curtas **põe o seu contexto de tenant**:
 * `evt_acoes` tem `FORCE ROW LEVEL SECURITY` e quem a escreve é `kamba_app`,
 * que é `NOBYPASSRLS`. Não se herda o contexto de quem chama — `once` é
 * chamado de dentro e de fora da transacção do consumo, e depender de um `SET
 * LOCAL` alheio fazia a mesma função funcionar num sítio e falhar no outro.
 */
export async function once<T>(
  opcoes: OpcoesDaAccao,
  fn: () => Promise<T>,
): Promise<ResultadoDaAccao<T>> {
  const { bd, consumer, eventId, tenantId, accao } = opcoes;
  const chave = chaveDaAccao(consumer, eventId, accao);
  // Antes de qualquer `BEGIN`: ver `TransaccaoAlheiaError`.
  await exigirForaDeTransaccao(bd, chave);

  const abertura = await comContexto(bd, tenantId, async () => {
    const abriu = await bd.query(SQL_ABRIR_ACCAO, [chave, consumer, eventId, accao, tenantId]);
    if ((abriu.rowCount ?? 0) > 0) return { nossa: true as const };
    const { rows } = await bd.query(SQL_LER_ACCAO, [chave]);
    return { nossa: false as const, linha: rows[0] };
  });

  if (!abertura.nossa) {
    if (abertura.linha === undefined) {
      // A chave colidiu e a linha **não se vê**. Com RLS, isso tem um
      // significado só: a chave existe noutro tenant. Não se repete o efeito
      // (a chave já foi dada a um terceiro) e não se finge que está feito —
      // lança-se, alto, porque a forma da chave inclui o `event_id` e uma
      // colisão entre tenants é defeito de construção da chave, não um caso a
      // tratar.
      throw new Error(
        `a chave ${chave} já existe e não é deste tenant: a chave de idempotência ` +
          'colidiu entre tenants, e repetir ou fingir o efeito eram os dois errados',
      );
    }
    const estado = abertura.linha.estado as EstadoDeAccao | undefined;
    if (estado === 'em_curso') {
      throw new Adiar(
        5,
        `a acção ${chave} está em curso: outro processo corre-a agora, ou morreu a meio`,
      );
    }
    // `feita` ou `falhada`: já se decidiu, e não se repete. Devolve-se o que
    // ficou guardado — incluindo `null`, que é o resultado de quem não guardou
    // nada.
    return { executou: false, resultado: (abertura.linha.resultado ?? null) as T | null };
  }

  let resultado: T;
  try {
    resultado = await fn();
  } catch (erro) {
    // A acção fica `falhada` **com** o motivo: sem isto, a chave ficava
    // `em_curso` para sempre e todas as re-entregas adiavam — o efeito nunca
    // acontecia e ninguém sabia porquê.
    const motivo = erro instanceof Error ? erro.message : String(erro);
    await comContexto(bd, tenantId, () =>
      bd.query(SQL_FECHAR_ACCAO, [chave, 'falhada', JSON.stringify({ erro: motivo })]),
    );
    throw erro;
  }
  await comContexto(bd, tenantId, () =>
    bd.query(SQL_FECHAR_ACCAO, [
      chave,
      'feita',
      resultado === undefined ? null : JSON.stringify(resultado),
    ]),
  );
  return { executou: true, resultado };
}

/**
 * Corre `passo` numa transacção curta com o contexto de tenant posto.
 *
 * Três instruções sempre pela mesma ordem — `BEGIN`, `set_config`, o passo — e
 * `ROLLBACK` em qualquer falha. Escrito uma vez porque o `once` precisa dela
 * três vezes, e três cópias divergiam na que se esquecesse do `ROLLBACK`.
 */
async function comContexto<T>(
  bd: ClienteSql,
  tenantId: string,
  passo: () => Promise<T>,
): Promise<T> {
  await bd.query('BEGIN');
  try {
    await bd.query(SQL_DEFINIR_TENANT, [tenantId, true]);
    const resultado = await passo();
    await bd.query('COMMIT');
    return resultado;
  } catch (erro) {
    try {
      await bd.query('ROLLBACK');
    } catch {
      /* a ligação já morreu; o erro de cima é o que explica */
    }
    throw erro;
  }
}
